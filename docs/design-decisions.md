# Design decisions

Rationale for key choices so future contributors understand the "why". Repo-man is format-extensible; the ideas below apply across package formats, with APT as the first implementation.

## Clients always see latest packages

Format metadata (e.g. Release, Packages for APT) must not be stale. We either proxy metadata from upstream on each request or cache it with a short TTL and revalidate. We never serve long-lived cached metadata by default. Package files are cached on demand and pruned to latest N; the catalog is always up to date.

## Pull-through cache vs full mirror

A full mirror would download every package from upstream and keep disk usage unbounded. We chose a **pull-through cache**: we only store packages that have been requested at least once, and we keep only the **latest N versions** of each package (configurable N). This keeps disk usage bounded while still allowing "install any version available upstream" (metadata is fresh, so clients see all versions; we fetch and cache on first request).

## Latest-N retention

Prune runs (manually or automatically after cache writes) remove older versions of each package, keeping the N newest. Version comparison is format-specific (e.g. Debian version for APT). N is configurable (`CACHE_VERSIONS_PER_PACKAGE`, default 3). Trade-off: less disk vs. fewer old versions in cache. Metadata remains fresh, so clients can request an old version; we fetch it from upstream again if it was pruned.

## Path-prefix multi-repo model

One service can serve multiple upstreams and local repos, for one or more formats. Each upstream (and each local repo) has a **path prefix** (e.g. `/ubuntu/`, `/k8s/v1.34/`). Clients point at the same host with different paths (e.g. APT `sources.list` entries). Storage is namespaced by upstream id or local prefix so repos do not mix. Prune is per upstream.

## Storage abstraction

All artifact storage goes through a single interface (`StorageBackend`: get, put, list_prefix, delete, exists). This keeps format and serve logic agnostic of where data lives. We implement local filesystem first; adding S3 or another backend is a new implementation of the same interface, with no change to cache/publish/serve logic.

## Format abstraction

Package formats are implemented as backends that know how to parse metadata, fetch/cache packages, publish, and prune. The CLI and serve layer call into them via a common interface (`FormatBackend`). APT is the included format; adding another (e.g. RPM) is a new backend under `formats/`, plus CLI and config for that format.

## Prometheus and single registry

We use `prometheus_client` and the default registry. All metrics (HTTP, cache, prune, publish, storage) are registered there. The serve layer exposes `/metrics` on the same HTTP server as the repo. This gives one scrape target and one place to see all instrumentation.

## Config: env and optional file

Configuration is 12-factor: env vars for repo root, config path, cache retention N, etc. An optional YAML/TOML file holds the list of upstreams (and later local repo definitions). Upstreams can be added via CLI and persisted to that file. This fits both single-node and container deployments.

## Ansible-friendly CLI

State-changing commands support `--check` (dry-run) and `--output json` with a `changed` boolean so Ansible can use `changed_when: (result.stdout | from_json).changed`. Commands are idempotent where possible (e.g. add-upstream no-op if same config already exists).
