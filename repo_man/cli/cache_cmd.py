"""cache command group: add-upstream, list, prune, remove-upstream."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import click

logger = logging.getLogger(__name__)

from repo_man import config as config_module
from repo_man.disk import get_repo_disk_usage_bytes
from repo_man.formats.apt.cache import free_disk_until_under_watermark, prune_upstream
from repo_man.hash_store import create_package_hash_store
from repo_man.metrics import prune_duration_seconds, prune_packages_removed_total, prune_runs_total
from repo_man.storage.local import LocalStorageBackend


def _config_path(ctx: click.Context) -> Path | None:
    p = ctx.obj.get("config_path")
    if p is not None:
        return Path(p)
    p = config_module.get_config_path()
    if p is not None:
        return p
    root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    return root / "config.yaml"


@click.group("cache")
def cache() -> None:
    """Manage pull-through cache upstreams and pruning."""
    pass


@cache.command("add-upstream")
@click.option("--name", required=True, help="Upstream name.")
@click.option("--url", "base_url", required=True, help="Base URL of upstream APT repo.")
@click.option(
    "--layout",
    type=click.Choice(["classic", "single-stream"]),
    default="classic",
    help="Layout type.",
)
@click.option("--path-prefix", default="/", help="Path prefix for serving (e.g. /ubuntu/).")
@click.option("--suites", default="", help="Comma-separated suites (classic only).")
@click.option("--components", default="", help="Comma-separated components (classic only).")
@click.option("--archs", default="amd64", help="Comma-separated architectures.")
@click.pass_context
def add_upstream(
    ctx: click.Context,
    name: str,
    base_url: str,
    layout: str,
    path_prefix: str,
    suites: str,
    components: str,
    archs: str,
) -> None:
    """Register an upstream APT repo."""
    check_mode = ctx.obj.get("check_mode", False)
    out_json = ctx.obj.get("output_json")
    config_path = _config_path(ctx)
    upstreams = list(config_module.get_upstreams_from_config(config_path) if config_path else [])
    new_entry = {
        "name": name,
        "url": base_url,
        "base_url": base_url,
        "layout": layout,
        "path_prefix": path_prefix.rstrip("/") or "/",
        "suites": [s.strip() for s in suites.split(",") if s.strip()],
        "components": [c.strip() for c in components.split(",") if c.strip()],
        "archs": [a.strip() for a in archs.split(",") if a.strip()],
    }
    existing = next((u for u in upstreams if u.get("name") == name), None)
    if existing and (
        existing.get("url") == base_url
        and existing.get("path_prefix") == new_entry["path_prefix"]
        and existing.get("layout") == layout
    ):
        if out_json:
            out_json(changed=False, message=f"Upstream {name} unchanged", details={"name": name})
        else:
            click.echo(f"Upstream {name} already configured (no change).")
        return
    if check_mode:
        if out_json:
            out_json(changed=True, message=f"Would add upstream {name}", details={"name": name, "url": base_url})
        else:
            click.echo(f"Would add upstream {name} -> {base_url}")
        return
    if existing:
        upstreams = [u for u in upstreams if u.get("name") != name]
        logger.info("Removed upstream: name=%s (replaced)", name)
    upstreams.append(new_entry)
    if config_path:
        config_module.save_upstreams_to_config(config_path, upstreams)
    logger.info("Added upstream: name=%s url=%s", name, base_url)
    if out_json:
        out_json(changed=True, message=f"Added upstream {name}", details={"name": name})
    else:
        click.echo(f"Added upstream {name}.")


@cache.command("remove-upstream")
@click.option("--name", "upstream_name", required=True, help="Upstream name to remove.")
@click.pass_context
def remove_upstream(ctx: click.Context, upstream_name: str) -> None:
    """Remove an upstream APT repo by name."""
    check_mode = ctx.obj.get("check_mode", False)
    out_json = ctx.obj.get("output_json")
    config_path = _config_path(ctx)
    if not config_path:
        if out_json:
            out_json(changed=False, message="No config file", details={})
        else:
            click.echo("No config file.")
        return
    upstreams = list(config_module.get_upstreams_from_config(config_path))
    before = len(upstreams)
    upstreams = [u for u in upstreams if u.get("name") != upstream_name]
    if len(upstreams) == before:
        if out_json:
            out_json(changed=False, message=f"Upstream {upstream_name} not found", details={"name": upstream_name})
        else:
            click.echo(f"Upstream {upstream_name} not found.")
        return
    if check_mode:
        if out_json:
            out_json(changed=True, message=f"Would remove upstream {upstream_name}", details={"name": upstream_name})
        else:
            click.echo(f"Would remove upstream {upstream_name}.")
        return
    config_module.save_upstreams_to_config(config_path, upstreams)
    logger.info("Removed upstream: name=%s", upstream_name)
    if out_json:
        out_json(changed=True, message=f"Removed upstream {upstream_name}", details={"name": upstream_name})
    else:
        click.echo(f"Removed upstream {upstream_name}.")


@cache.command("list")
@click.pass_context
def list_upstreams(ctx: click.Context) -> None:
    """List configured upstreams."""
    config_path = _config_path(ctx)
    upstreams = config_module.get_upstreams_from_config(config_path) if config_path else []
    if not upstreams:
        click.echo("No upstreams configured.")
        return
    for u in upstreams:
        name = u.get("name", "?")
        url = u.get("url", u.get("base_url", "?"))
        prefix = u.get("path_prefix", "/")
        layout = u.get("layout", "classic")
        click.echo(f"  {name}: {url} (prefix={prefix}, layout={layout})")


@cache.command("prune")
@click.option("--upstream", default=None, help="Only prune this upstream by name.")
@click.pass_context
def prune(ctx: click.Context, upstream: str | None) -> None:
    """Run prune job (keep latest N versions per package)."""
    check_mode = ctx.obj.get("check_mode", False)
    out_json = ctx.obj.get("output_json")
    if check_mode:
        if out_json:
            out_json(changed=True, message="Would run prune", details={"upstream": upstream})
        else:
            click.echo("Would run prune (no changes).")
        return
    repo_root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    storage = LocalStorageBackend(repo_root)
    config_path = _config_path(ctx)
    upstreams_list = config_module.get_upstreams_from_config(config_path) if config_path else []
    keep_n = config_module.get_cache_versions_per_package()
    if upstream is not None:
        upstreams_list = [u for u in upstreams_list if u.get("name") == upstream]
    upstream_ids = [u["name"] for u in upstreams_list if u.get("name")]

    # Disk watermark: free cache (never published) when over high watermark
    watermark_removed = 0
    high_watermark = config_module.get_disk_high_watermark_bytes(config_path)
    if high_watermark is not None and upstream_ids:
        usage = get_repo_disk_usage_bytes(repo_root)
        if usage > high_watermark:
            logger.info(
                "Disk over high watermark: usage=%s bytes watermark=%s bytes; freeing cache (published kept)",
                usage,
                high_watermark,
            )
            package_hash_store = create_package_hash_store(
                config_module.get_package_hash_store_type(config_path),
                redis_url=config_module.get_redis_url(config_path),
                local_db_path=repo_root / "hash_store.db",
            )
            watermark_removed = free_disk_until_under_watermark(
                storage,
                upstream_ids,
                high_watermark,
                lambda: get_repo_disk_usage_bytes(repo_root),
                hash_store=package_hash_store,
            )
            if watermark_removed:
                logger.info("Freed %s cached package(s) to bring disk under watermark", watermark_removed)

    start = time.perf_counter()
    prune_runs_total.inc()
    removed = 0
    for u in upstreams_list:
        name = u.get("name")
        if name:
            r = prune_upstream(storage, name, keep_n)
            removed += r
            if r:
                prune_packages_removed_total.labels(upstream=name).inc(r)
    prune_duration_seconds.observe(time.perf_counter() - start)
    total_removed = watermark_removed + removed
    logger.info(
        "Prune completed: removed %s package(s) from %s upstream(s)",
        total_removed,
        len(upstreams_list),
    )
    if out_json:
        out_json(changed=total_removed > 0, message="Prune completed", details={"removed": total_removed})
    else:
        click.echo(f"Prune completed (removed {total_removed} package(s)).")
