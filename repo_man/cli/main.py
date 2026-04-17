"""CLI entry point and global options."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import click

from repo_man import __version__
from repo_man.cli import cache_cmd, config_cmd, publish_cmd, serve_cmd


def _output_json_result(obj: dict[str, Any]) -> None:
    """Print JSON result for Ansible (--output json)."""
    click.echo(json.dumps(obj, indent=0))


@click.group()
@click.version_option(__version__, prog_name="repo-man")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, exists=False),
    default=None,
    envvar="REPO_MIRROR_CONFIG",
    help="Path to config file (YAML/TOML).",
)
@click.option(
    "--repo-root",
    type=click.Path(path_type=Path, exists=False),
    default=None,
    envvar="REPO_MIRROR_REPO_ROOT",
    help="Repo root directory for storage.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
@click.option(
    "--check",
    "check_mode",
    is_flag=True,
    help="Dry-run: do not modify state; report what would be done.",
)
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format; 'json' for Ansible changed_when.",
)
@click.pass_context
def main(
    ctx: click.Context,
    config_path: Path | None,
    repo_root: Path | None,
    verbose: bool,
    check_mode: bool,
    output_format: str,
) -> None:
    """Linux package mirror and publishing tool (APT pull-through cache + local publish)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["repo_root"] = repo_root
    ctx.obj["verbose"] = verbose
    ctx.obj["check_mode"] = check_mode
    ctx.obj["output_format"] = output_format
    ctx.obj["output_json"] = lambda **kwargs: _output_json_result(kwargs) if output_format == "json" else None


main.add_command(serve_cmd.serve)
main.add_command(cache_cmd.cache)
main.add_command(publish_cmd.publish)
main.add_command(config_cmd.config_group)
