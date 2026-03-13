# repo-man

Extensible package repository manager: pull-through cache (latest-N per package), local publish, and a single HTTP service. Handles packages through pluggable format and storage backends; APT is included—add other formats and backends as needed. [MIT License](LICENSE).

## Install (Docker, recommended for local run)

**Run the server (repo data in `./repo_data`):**

```bash
docker run -d \
  --name repo-man \
  -p 8080:8080 \
  -v "$(pwd)/repo_data:/data" \
  -e REPO_MIRROR_REPO_ROOT=/data \
  awesomeit/repo-man:latest
```

- Server listens on **http://localhost:8080**. Metrics: **http://localhost:8080/metrics**.
- To add upstreams or publish packages, run CLI in the same container:
  ```bash
  docker exec repo-man repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ --layout classic --path-prefix /ubuntu --suites noble --components main --archs amd64
  docker exec repo-man repo-man publish add --path-prefix /local/ /path/on/host/pkg.deb   # copy .deb into container first, or use a bind mount
  ```
- Or use [Compose](compose.yaml): set the service image to `awesomeit/repo-man:latest`, then `docker compose up -d`. See [docs/examples.md](docs/examples.md) for more.

## Install from source (development)

For hacking or running without Docker:

```bash
uv sync
uv run repo-man --help
uv run pytest
```

- **Documentation:** [docs/README.md](docs/README.md) — architecture, design decisions, formats (incl. APT), deployment examples, extension guide, operations, support policy, CRA compliance.
- **Security:** [SECURITY.md](SECURITY.md) — vulnerability reporting and coordinated disclosure.

## Configuration

- `REPO_MIRROR_REPO_ROOT` – repo root directory (default: `./repo_data`)
- `REPO_MIRROR_CONFIG` – path to config file (YAML/TOML)
- `CACHE_VERSIONS_PER_PACKAGE` – keep latest N versions per package (default: 3)

## Example (APT format)

With **Docker**: use `docker exec repo-man repo-man <command> ...` for cache/publish; the server is already running. With **source**: run the CLI directly:

```bash
# Add upstream, publish packages, serve (omit 'serve' when using Docker; container already runs it)
repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ --layout classic --path-prefix /ubuntu/
repo-man publish add --path-prefix /local/ ./pkg.deb
repo-man serve --port 8080
```

Prometheus metrics: `GET /metrics` on the same server.

## Docker integration test

Run the service in Compose, then a client container that uses it to install packages (pull-through from upstream repos). The integration test uses Ubuntu and the APT format:

```bash
docker compose -f tests/docker/compose.integration.yaml up -d
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client
```

See [tests/docker/README.md](tests/docker/README.md) for details.
