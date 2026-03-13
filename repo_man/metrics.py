"""Prometheus metrics: single registry and metric definitions."""

from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

# Use default registry so /metrics exports everything
def get_metrics_output() -> str:
    """Return Prometheus text format for /metrics endpoint."""
    return generate_latest(REGISTRY).decode("utf-8")

# HTTP serve
http_requests_total = Counter(
    "repo_man_http_requests_total",
    "Total HTTP requests",
    ["method", "path_prefix", "status"],
)
http_request_duration_seconds = Histogram(
    "repo_man_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["path_prefix"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Cache
cache_requests_total = Counter(
    "repo_man_cache_requests_total",
    "Cache lookups",
    ["result"],  # hit | miss
)
cache_upstream_fetches_total = Counter(
    "repo_man_cache_upstream_fetches_total",
    "Upstream .deb fetches",
    ["upstream"],
)
cache_upstream_fetch_duration_seconds = Histogram(
    "repo_man_cache_upstream_fetch_duration_seconds",
    "Upstream fetch duration",
    ["upstream"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)
cache_upstream_fetch_errors_total = Counter(
    "repo_man_cache_upstream_fetch_errors_total",
    "Upstream fetch errors",
    ["upstream"],
)
packages_pulled_from_upstream_total = Counter(
    "repo_man_packages_pulled_from_upstream_total",
    "Packages fetched from upstream and stored (pull-through)",
    ["upstream"],
)
upstream_last_access_timestamp_seconds = Gauge(
    "repo_man_upstream_last_access_timestamp_seconds",
    "Unix timestamp of last fetch from this upstream (metadata or package).",
    ["upstream"],
)
cache_package_hash_mismatch_total = Counter(
    "repo_man_cache_package_hash_mismatch_total",
    "Cached packages dropped because remote hash changed (re-fetch on next request)",
    ["upstream"],
)
packages_served_total = Counter(
    "repo_man_packages_served_total",
    "Packages (.deb) served to clients",
    ["path_prefix"],
)
client_packages_served_total = Counter(
    "repo_man_client_packages_served_total",
    "Packages (.deb) served to each client (client = IP or hostname from reverse DNS)",
    ["client"],
)
client_last_served_timestamp_seconds = Gauge(
    "repo_man_client_last_served_timestamp_seconds",
    "Unix timestamp when last package was served to each client",
    ["client"],
)
metadata_requests_total = Counter(
    "repo_man_metadata_requests_total",
    "Metadata requests",
    ["type", "result"],
)

# Prune
prune_runs_total = Counter("repo_man_prune_runs_total", "Prune job runs")
prune_packages_removed_total = Counter(
    "repo_man_prune_packages_removed_total",
    "Packages removed by prune",
    ["upstream"],
)
prune_duration_seconds = Histogram(
    "repo_man_prune_duration_seconds",
    "Prune job duration",
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0),
)
prune_errors_total = Counter("repo_man_prune_errors_total", "Prune errors")

# Publish
publish_uploads_total = Counter(
    "repo_man_publish_uploads_total",
    "Packages published",
    ["path_prefix"],
)
publish_errors_total = Counter(
    "repo_man_publish_errors_total",
    "Publish errors",
    ["path_prefix"],
)
publish_duration_seconds = Histogram(
    "repo_man_publish_duration_seconds",
    "Publish operation duration",
    ["path_prefix"],
    buckets=(0.1, 0.5, 1.0, 2.0),
)

# Storage
storage_operations_total = Counter(
    "repo_man_storage_operations_total",
    "Storage operations",
    ["operation", "backend"],
)
storage_operation_duration_seconds = Histogram(
    "repo_man_storage_operation_duration_seconds",
    "Storage operation duration",
    ["operation", "backend"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5),
)
storage_errors_total = Counter(
    "repo_man_storage_errors_total",
    "Storage errors",
    ["operation", "backend"],
)
