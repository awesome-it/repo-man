"""config command group: show, validate."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from repo_man import config as config_module

logger = logging.getLogger(__name__)


@click.group("config")
def config_group() -> None:
    """Show or validate configuration."""
    pass


@config_group.command("show")
@click.pass_context
def show(ctx: click.Context) -> None:
    """Print effective config (repo root, upstreams, retention N, etc.)."""
    cfg = config_module.get_effective_config(
        config_path_override=ctx.obj.get("config_path"),
        repo_root_override=ctx.obj.get("repo_root"),
    )
    if ctx.obj.get("output_format") == "json":
        click.echo(json.dumps(cfg, indent=2))
    else:
        click.echo("Effective config:")
        click.echo(f"  repo_root: {cfg['repo_root']}")
        click.echo(f"  config_file: {cfg['config_file']}")
        click.echo(f"  cache_versions_per_package: {cfg['cache_versions_per_package']}")
        click.echo(f"  metadata_ttl_seconds: {cfg['metadata_ttl_seconds']}")
        click.echo(f"  disk_high_watermark_bytes: {cfg.get('disk_high_watermark_bytes')}")
        click.echo(f"  serve: {cfg['serve_bind']}:{cfg['serve_port']}")
        click.echo(f"  upstreams: {len(cfg['upstreams'])} configured")


@config_group.command("validate")
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate config file and exit 0/1."""
    config_path = ctx.obj.get("config_path") or config_module.get_config_path()
    if not config_path or not config_path.exists():
        logger.error("Config validate failed: no config file path or file missing")
        click.echo("No config file to validate.", err=True)
        raise SystemExit(1)
    data = config_module.load_config_file(config_path)
    if not data:
        logger.error("Config validate failed: config file empty or invalid path=%s", config_path)
        click.echo("Config file is empty or invalid.", err=True)
        raise SystemExit(1)
    click.echo("Config file is valid.")
    raise SystemExit(0)
