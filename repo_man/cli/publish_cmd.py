"""publish command group: add, list."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import click

from repo_man import config as config_module

logger = logging.getLogger(__name__)
from repo_man.formats.apt.publish import publish_packages
from repo_man.metrics import publish_duration_seconds, publish_uploads_total
from repo_man.storage.local import LocalStorageBackend


@click.group("publish")
def publish() -> None:
    """Publish local .deb packages to a repo path prefix."""
    pass


@publish.command("add")
@click.option("--path-prefix", required=True, help="Path prefix for the local repo (e.g. /local/).")
@click.option("--suite", default="stable", help="Suite name.")
@click.option("--component", default="main", help="Component name.")
@click.option("--arch", default="amd64", help="Architecture.")
@click.argument("deb_files", nargs=-1, type=click.Path(path_type=Path, exists=True))
@click.pass_context
def add(
    ctx: click.Context,
    path_prefix: str,
    suite: str,
    component: str,
    arch: str,
    deb_files: tuple[Path, ...],
) -> None:
    """Ingest .deb(s) into a local repo; (re)generate Packages and Release."""
    check_mode = ctx.obj.get("check_mode", False)
    out_json = ctx.obj.get("output_json")
    if check_mode:
        if out_json:
            out_json(
                changed=True,
                message="Would publish packages",
                details={"path_prefix": path_prefix, "count": len(deb_files)},
            )
        else:
            click.echo(f"Would publish {len(deb_files)} package(s) to {path_prefix}")
        return
    if not deb_files:
        logger.error("Publish failed: no .deb files given")
        click.echo("No .deb files given.", err=True)
        raise SystemExit(1)
    repo_root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    storage = LocalStorageBackend(repo_root)
    start = time.perf_counter()
    changed = publish_packages(
        path_prefix,
        list(deb_files),
        suite,
        component,
        arch,
        storage,
    )
    publish_uploads_total.labels(path_prefix=path_prefix).inc(len(deb_files))
    publish_duration_seconds.labels(path_prefix=path_prefix).observe(time.perf_counter() - start)
    if changed:
        logger.info(
            "Published %s package(s) to path_prefix=%s suite=%s",
            len(deb_files),
            path_prefix,
            suite,
        )
    if out_json:
        out_json(
            changed=changed,
            message=f"Published {len(deb_files)} package(s)",
            details={"count": len(deb_files)},
        )
    else:
        click.echo(f"Published {len(deb_files)} package(s) to {path_prefix}.")


@publish.command("list")
@click.option("--path-prefix", required=True, help="Path prefix of the local repo.")
@click.pass_context
def list_packages(ctx: click.Context, path_prefix: str) -> None:
    """List packages in the local repo at that prefix."""
    # Implementation in step 3
    click.echo(f"Packages at {path_prefix}: (implementation in step 3)")
