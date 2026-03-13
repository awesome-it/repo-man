# repo-man

Extensible package repository manager: pull-through cache (latest-N per package), local publish, and a single HTTP service. Handles packages through pluggable format and storage backends; APT is included—add other formats and backends as needed. [MIT License](LICENSE).

## Quick start

- **Install (uv):** `uv sync`
- **Run CLI:** `uv run repo-man --help`
- **Run tests:** `uv run pytest` (or `uv run pytest --cov`)
- **Documentation:** [docs/README.md](docs/README.md) — architecture, design decisions, formats (incl. APT), extension guide, operations, support policy, CRA compliance.
- **Security:** [SECURITY.md](SECURITY.md) — vulnerability reporting and coordinated disclosure.

## Configuration

- `REPO_MIRROR_REPO_ROOT` – repo root directory (default: `./repo_data`)
- `REPO_MIRROR_CONFIG` – path to config file (YAML/TOML)
- `CACHE_VERSIONS_PER_PACKAGE` – keep latest N versions per package (default: 3)

## Example (APT format)

```bash
# Add upstream, publish packages, serve
uv run repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ --layout classic --path-prefix /ubuntu/
uv run repo-man publish add --path-prefix /local/ ./pkg.deb
uv run repo-man serve --port 8080
```

Prometheus metrics: `GET /metrics` on the same server.

## Docker integration test

Run the service in Compose, then a client container that uses it to install packages (pull-through from upstream repos). The integration test uses Ubuntu and the APT format:

```bash
docker compose -f tests/docker/compose.integration.yaml up -d
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client
```

See [tests/docker/README.md](tests/docker/README.md) for details.
