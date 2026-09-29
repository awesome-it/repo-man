"""status command: show last-known or live-check upstream health."""

from __future__ import annotations

import json
import time
from pathlib import Path

import click

from repo_man import config as config_module
from repo_man.health import (
    UpstreamHealthResult,
    build_client_urls,
    load_status,
    run_health_checks,
    status_path,
)


def _config_path(ctx: click.Context) -> Path:
    p = ctx.obj.get("config_path")
    if p is not None:
        return Path(p)
    p = config_module.get_config_path()
    if p is not None:
        return p
    root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    return root / "config.yaml"


def _format_age(checked_at: float) -> str:
    if not checked_at:
        return "never"
    age = max(0, int(time.time() - checked_at))
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    if age < 86400:
        return f"{age // 3600}h ago"
    return f"{age // 86400}d ago"


def _print_result(r: UpstreamHealthResult) -> None:
    state = "healthy" if r.healthy else "unhealthy"
    click.echo(f"{r.name}: {state} (format={r.format}, prefix={r.path_prefix}, checked {_format_age(r.checked_at)})")
    for url in r.client_urls:
        click.echo(f"  client: {url}")
    if r.error:
        click.echo(f"  error: {r.error}")


@click.command("status")
@click.option(
    "--check",
    "do_check",
    is_flag=True,
    default=False,
    help="Live-probe each upstream now and update the status file (does not update serve /metrics).",
)
@click.option(
    "--no-default-upstreams",
    is_flag=True,
    default=False,
    help="Disable default upstreams when no config upstreams are present.",
)
@click.pass_context
def status(ctx: click.Context, do_check: bool, no_default_upstreams: bool) -> None:
    """Show health of configured upstreams (last-known, or live with --check)."""
    repo_root = config_module.get_repo_root(ctx.obj.get("repo_root"))
    config_path = _config_path(ctx)
    public_base_url = config_module.get_public_base_url(config_path)
    upstreams, _ = config_module.get_effective_upstreams(
        config_path,
        no_default_upstreams_flag=no_default_upstreams,
    )
    output_json = ctx.obj.get("output_format") == "json"

    if not upstreams:
        if output_json:
            click.echo(json.dumps({"upstreams": [], "message": "No upstreams configured"}, indent=2))
        else:
            click.echo("No upstreams configured.")
        raise SystemExit(0)

    results: list[UpstreamHealthResult]
    source: str

    if do_check:
        # CLI --check updates the status file only; Prometheus gauges live in the serve process.
        results = run_health_checks(
            upstreams,
            repo_root,
            public_base_url=public_base_url,
            update_metrics=False,
        )
        source = "live"
    else:
        stored = load_status(repo_root)
        if stored is None:
            msg = (
                f"No status file at {status_path(repo_root)}. "
                "Start `repo-man serve` or run `repo-man status --check`."
            )
            if output_json:
                click.echo(json.dumps({"error": msg, "upstreams": []}, indent=2))
            else:
                click.echo(msg, err=True)
            raise SystemExit(2)

        by_name = {
            str(u.get("name")): u
            for u in (stored.get("upstreams") or [])
            if isinstance(u, dict) and u.get("name")
        }
        results = []
        for u in upstreams:
            name = str(u.get("name") or "")
            raw = by_name.get(name)
            if raw is None:
                results.append(
                    UpstreamHealthResult(
                        name=name,
                        path_prefix=str(u.get("path_prefix") or "/"),
                        format=str(u.get("format") or "apt"),
                        healthy=False,
                        metadata_ok=False,
                        package_ok=False,
                        checked_at=0,
                        error="No probe result yet (not checked since serve started)",
                        client_urls=build_client_urls(u, public_base_url),
                    )
                )
            else:
                r = UpstreamHealthResult.from_dict(raw)
                # Refresh client URLs from current config/public_base_url
                r.client_urls = build_client_urls(u, public_base_url)
                results.append(r)
        source = "last-known"

    if output_json:
        payload = {
            "source": source,
            "status_file": str(status_path(repo_root)),
            "upstreams": [r.to_dict() for r in results],
        }
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(f"Upstream status ({source}):")
        for r in results:
            _print_result(r)

    if any(not r.healthy for r in results):
        raise SystemExit(1)
    raise SystemExit(0)
