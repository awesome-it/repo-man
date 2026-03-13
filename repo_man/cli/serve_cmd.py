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
@click.pass_context
def serve(ctx: click.Context, bind: str, port: int) -> None:
    """Run the HTTP server; serves APT repos by path prefix and /metrics."""
    repo_root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    config_path = _config_path(ctx)
    upstreams = config_module.get_upstreams_from_config(config_path) if config_path else []
    storage = LocalStorageBackend(repo_root)
    local_prefixes = []  # Could be from config later
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
    )
