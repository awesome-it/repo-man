"""publish command group: add, list."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import click

from repo_man import config as config_module

logger = logging.getLogger(__name__)
from repo_man.metrics import publish_duration_seconds, publish_uploads_total
from repo_man.storage.local import LocalStorageBackend


@click.group("publish")
def publish() -> None:
    """Publish local .deb packages to a repo path prefix."""
    pass


@publish.command("add")
@click.option("--path-prefix", required=True, help="Path prefix for the local repo (e.g. /local/).")
@click.option(
    "--format",
    "format_name",
    type=click.Choice(["apt", "rpm", "alpine"]),
    default="apt",
    help="Repo format (apt, rpm, alpine).",
)
@click.option("--suite", default="stable", help="Suite name (APT only).")
@click.option("--component", default="main", help="Component name (APT only).")
@click.option("--arch", default="amd64", help="Architecture (APT or RPM).")
@click.option("--branch", default="main", help="Branch (Alpine only, e.g. main, community).")
@click.argument("package_files", nargs=-1, type=click.Path(path_type=Path, exists=True))
@click.pass_context
def add(
    ctx: click.Context,
    path_prefix: str,
    format_name: str,
    suite: str,
    component: str,
    arch: str,
    branch: str,
    package_files: tuple[Path, ...],
) -> None:
    """Ingest packages into a local repo (.deb for APT, .rpm for RPM, .apk for Alpine)."""
    check_mode = ctx.obj.get("check_mode", False)
    out_json = ctx.obj.get("output_json")
    if check_mode:
        if out_json:
            out_json(
                changed=True,
                message="Would publish packages",
                details={"path_prefix": path_prefix, "format": format_name, "count": len(package_files)},
            )
        else:
            click.echo(f"Would publish {len(package_files)} package(s) to {path_prefix} (format={format_name})")
        return
    if not package_files:
        logger.error("Publish failed: no package files given")
        click.echo("No package files given.", err=True)
        raise SystemExit(1)
    repo_root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    if format_name == "apt":
        _publish_apt(repo_root, path_prefix, suite, component, arch, list(package_files), out_json)
    elif format_name == "rpm":
        _publish_rpm(repo_root, path_prefix, arch, list(package_files), out_json)
    elif format_name == "alpine":
        _publish_alpine(repo_root, path_prefix, branch, list(package_files), out_json)
    else:
        click.echo(f"Unknown format: {format_name}", err=True)
        raise SystemExit(1)


def _publish_apt(
    repo_root: Path,
    path_prefix: str,
    suite: str,
    component: str,
    arch: str,
    deb_files: list[Path],
    out_json,
) -> None:
    from repo_man.formats.apt.publish import publish_packages

    storage = LocalStorageBackend(repo_root)
    start = time.perf_counter()
    changed = publish_packages(path_prefix, deb_files, suite, component, arch, storage)
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
        out_json(changed=changed, message=f"Published {len(deb_files)} package(s)", details={"count": len(deb_files)})
    else:
        click.echo(f"Published {len(deb_files)} package(s) to {path_prefix}.")


def _publish_rpm(repo_root: Path, path_prefix: str, arch: str, rpm_files: list[Path], out_json) -> None:
    try:
        from repo_man.formats.rpm.publish import publish_packages as rpm_publish
    except ImportError:
        click.echo("Publish for format 'rpm' is not yet implemented.", err=True)
        raise SystemExit(1)
    storage = LocalStorageBackend(repo_root)
    start = time.perf_counter()
    changed = rpm_publish(path_prefix, rpm_files, arch, storage)
    publish_uploads_total.labels(path_prefix=path_prefix).inc(len(rpm_files))
    publish_duration_seconds.labels(path_prefix=path_prefix).observe(time.perf_counter() - start)
    if out_json:
        out_json(changed=changed, message=f"Published {len(rpm_files)} package(s)", details={"count": len(rpm_files)})
    else:
        click.echo(f"Published {len(rpm_files)} package(s) to {path_prefix}.")


def _publish_alpine(repo_root: Path, path_prefix: str, branch: str, apk_files: list[Path], out_json) -> None:
    try:
        from repo_man.formats.alpine.publish import publish_packages as alpine_publish
    except ImportError:
        click.echo("Publish for format 'alpine' is not yet implemented.", err=True)
        raise SystemExit(1)
    storage = LocalStorageBackend(repo_root)
    start = time.perf_counter()
    changed = alpine_publish(path_prefix, apk_files, branch, storage)
    publish_uploads_total.labels(path_prefix=path_prefix).inc(len(apk_files))
    publish_duration_seconds.labels(path_prefix=path_prefix).observe(time.perf_counter() - start)
    if out_json:
        out_json(changed=changed, message=f"Published {len(apk_files)} package(s)", details={"count": len(apk_files)})
    else:
        click.echo(f"Published {len(apk_files)} package(s) to {path_prefix}.")


@publish.command("list")
@click.option("--path-prefix", required=True, help="Path prefix of the local repo.")
@click.pass_context
def list_packages(ctx: click.Context, path_prefix: str) -> None:
    """List packages in the local repo at that prefix."""
    # Implementation in step 3
    click.echo(f"Packages at {path_prefix}: (implementation in step 3)")
