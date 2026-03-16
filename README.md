# repo-man

**Package repository manager** for the office, datacenter, or pipeline: **pull-through cache**, **self-publishing**, and **metrics** in one service. One HTTP endpoint for your network; pluggable formats and storage (APT included). [MIT License](LICENSE).

- **Pull-through cache** — Packages and metadata are fetched from upstream on first request and cached; configurable latest-N retention and disk watermark. No full mirror, no wasted bandwidth.
- **Self-publishing** — Ingest and serve your own packages (e.g. internal .deb) alongside cached upstreams under path prefixes you define.
- **Metrics** — Prometheus `/metrics` on the same server: request counts, cache hit/miss, upstream fetch duration, prune and publish stats. **Client statistics** (packages served per client, last-served timestamp) let you see which hosts use the cache and alert when a host stops updating. See [docs/client-metrics.md](docs/client-metrics.md).

## Install (Docker, recommended)

**Run the server (repo data in `./repo_data`):**

```bash
docker run -d \
  --name repo-man \
  -p 8080:8080 \
  -v "$(pwd)/repo_data:/data" \
  -e REPO_MIRROR_REPO_ROOT=/data \
  awesomeit/repo-man:latest
```

- Listens on **http://localhost:8080**; Prometheus scrape target **http://localhost:8080/metrics**.
- Add upstreams or publish packages via the CLI in the same container:
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

| Variable | Description | Default |
|----------|-------------|---------|
| `REPO_MIRROR_REPO_ROOT` | Repo root (cache + published). | `./repo_data` |
| `REPO_MIRROR_CONFIG` | Config file path (YAML/TOML). | — |
| `CACHE_VERSIONS_PER_PACKAGE` | Latest N versions per package (retention). | 3 |
| `REPO_MIRROR_NO_DEFAULT_UPSTREAMS` | Disable default upstreams when no config (set to `1` or `true`). | — |

Full reference: [docs/operations.md](docs/operations.md).

### No config: default upstreams

If you **don’t provide a config file**, repo-man uses built-in **default upstreams** so clients can use the mirror immediately with minimal setup:

| Path prefix | Format | Use in clients |
|-------------|--------|----------------|
| `/ubuntu` | APT | `deb http://HOST:8080/ubuntu noble main` (jammy, noble, noble-updates, noble-security) |
| `/debian` | APT | `deb http://HOST:8080/debian bookworm main` (bookworm, bookworm-updates) |
| `/rocky9` | RPM | `baseurl=http://HOST:8080/rocky9` (Rocky Linux 9 BaseOS) |
| `/alpine` | Alpine | `http://HOST:8080/alpine` (Alpine 3.19 main) |

To **disable** default upstreams (e.g. you only want upstreams from your own config): set **`REPO_MIRROR_NO_DEFAULT_UPSTREAMS=1`**, pass **`--no-default-upstreams`** to `repo-man serve`, or create a config file with **`disable_default_upstreams: true`**. Providing a config file that defines any upstreams also disables defaults (only your configured upstreams are used).

## Example

With **no config**, just run the server; default upstreams (Ubuntu, Debian, Rocky 9, Alpine) are used and clients can point at the path prefixes above.

With **Docker**, run cache/publish via `docker exec repo-man repo-man <command> ...`; the server is already up. From **source**:

```bash
# Optional: add more upstreams or override defaults
repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ --format apt --layout classic --path-prefix /ubuntu --suites noble --components main --archs amd64
repo-man publish add --path-prefix /local/ ./pkg.deb
repo-man serve --port 8080
```

Metrics are exposed on the same port: `GET /metrics` (Prometheus).

## Docker integration test

Run the service in Compose, then a client container that uses it to install packages (pull-through from upstream repos). The integration test uses Ubuntu and the APT format:

```bash
docker compose -f tests/docker/compose.integration.yaml up -d
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client
```

See [tests/docker/README.md](tests/docker/README.md) for details.
