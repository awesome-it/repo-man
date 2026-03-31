"""serve command: run HTTP server for APT repo and /metrics."""

from __future__ import annotations

from pathlib import Path

import click

from repo_man import config as config_module
from repo_man.disk import get_repo_disk_usage_bytes
from repo_man.hash_store import create_package_hash_store
from repo_man.serve import run_server
from repo_man.storage.local import LocalStorageBackend


def _config_path(ctx: click.Context):
    from pathlib import Path
    p = ctx.obj.get("config_path")
    if p is not None:
        return Path(p)
    p = config_module.get_config_path()
    if p is not None:
        return p
    root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    return root / "config.yaml"


@click.command("serve")
@click.option("--bind", default="0.0.0.0", help="Bind address.")
@click.option("--port", type=int, default=8080, help="Port.")
@click.option(
    "--no-default-upstreams",
    is_flag=True,
    default=False,
    help="Disable default upstreams (Ubuntu, Debian, Rocky 9, Alpine). Use with config or REPO_MIRROR_NO_DEFAULT_UPSTREAMS.",
)
@click.option(
    "--enable-api",
    is_flag=True,
    default=None,
    help="Enable the REST API under /api/v1 (publish, health). Off by default. See REPO_MIRROR_ENABLE_API or config api.enable.",
)
@click.option(
    "--access-log/--no-access-log",
    default=False,
    help="Enable/disable per-request uvicorn access logs (default: disabled).",
)
@click.pass_context
def serve(
    ctx: click.Context,
    bind: str,
    port: int,
    no_default_upstreams: bool,
    enable_api: bool | None,
    access_log: bool,
) -> None:
    """Run the HTTP server; serves repos by path prefix and /metrics. With no config, uses default upstreams."""
    repo_root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    config_path = _config_path(ctx)
    upstreams, used_defaults = config_module.get_effective_upstreams(
        config_path,
        no_default_upstreams_flag=no_default_upstreams,
    )
    if used_defaults:
        click.echo(
            "Using default upstreams: /ubuntu (Ubuntu), /debian (Debian), /rocky9 (RPM), /alpine (Alpine). "
            "Disable with --no-default-upstreams or REPO_MIRROR_NO_DEFAULT_UPSTREAMS=1",
            err=True,
        )
    storage = LocalStorageBackend(repo_root)
    local_prefixes = []  # Could be from config later
    api_enabled = enable_api if enable_api is not None else config_module.get_enable_api(config_path)
    if api_enabled:
        # Serve published content under /local so API-published repos are visible to clients
        local_prefixes = ["/local"]
    metadata_ttl_seconds = config_module.get_metadata_ttl_seconds(config_path)
    store_type = config_module.get_package_hash_store_type(config_path)
    redis_url = config_module.get_redis_url(config_path)
    package_hash_store = create_package_hash_store(
        store_type,
        redis_url=redis_url,
        local_db_path=Path(repo_root) / "hash_store.db",
    )
    disk_high_watermark_bytes = config_module.get_disk_high_watermark_bytes(config_path)
    get_disk_usage_fn = lambda: get_repo_disk_usage_bytes(repo_root)
    keep_versions_per_package = config_module.get_cache_versions_per_package()
    if api_enabled:
        click.echo("API enabled (/api/v1). Any client that can reach the API can publish; secure it externally.", err=True)
    click.echo(f"Serving on http://{bind}:{port}")
    run_server(
        bind,
        port,
        storage,
        upstreams,
        local_prefixes,
        metadata_ttl_seconds,
        package_hash_store,
        disk_high_watermark_bytes=disk_high_watermark_bytes,
        get_disk_usage_fn=get_disk_usage_fn,
        keep_versions_per_package=keep_versions_per_package,
        enable_api=api_enabled,
        access_log=access_log,
    )
