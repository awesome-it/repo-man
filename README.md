# repo-man

A simple yet flexible and modern Linux repository pull-through cache and local repo server.
[MIT License](LICENSE).

> **Development is internal; GitHub is a read-only mirror.** Issues and pull requests opened here are not monitored.

- **Pull-through cache** — Packages and metadata are fetched from upstream on first request and cached; configurable latest-N retention and disk watermark. No full mirror, no wasted bandwidth.
- **Self-publishing** — Ingest and serve your own packages (e.g. internal .deb) alongside cached upstreams under path prefixes you define. Publish via CLI or, when enabled, via the HTTP API (e.g. from CI).
- **Metrics** — Prometheus `/metrics` included: request counts, cache hit/miss, upstream fetch duration, prune and publish stats.
- **Client statistics** (packages served per client, last-served timestamp) let you see which hosts use the cache and alert when a host stops updating. See [docs/client-metrics.md](docs/client-metrics.md).

## Install (Docker, recommended)

**Run the server (repo data in `./repo_data`):**

```bash
docker run -d \
  --name repo-man \
  -p 8080:8080 \
  awesomeit/repo-man:latest
```

The included default are a good start.

- Listens on **http://localhost:8080**; Prometheus scrape target **http://localhost:8080/metrics**.
- Add upstreams or publish packages via the CLI in the same container, or (if the API is enabled) via `POST /api/v1/publish`:
  ```bash
  docker exec repo-man repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ --layout classic --path-prefix /ubuntu --suites noble --components main --archs amd64
  docker exec repo-man repo-man publish add --path-prefix /local/ /path/on/host/pkg.deb   # copy .deb into container first, or use a bind mount
  # Publish via API (start container with --enable-api or REPO_MIRROR_ENABLE_API=1):
  curl -X POST -F path_prefix=/local/ -F format=apt -F suite=stable -F component=main -F arch=amd64 -F "packages=@pkg.deb" http://host:8080/api/v1/publish
  ```
- Or use [Compose](compose.yaml): set the service image to `awesomeit/repo-man:latest`, then `docker compose up -d`. See [docs/examples.md](docs/examples.md) for more.

## Install from source (development)

Running without Docker:

```bash
uv sync
uv run repo-man --help
uv run pytest
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `REPO_MIRROR_REPO_ROOT` | Repo root (cache + published). | `./repo_data` |
| `REPO_MIRROR_CONFIG` | Config file path (YAML/TOML). | — |
| `CACHE_VERSIONS_PER_PACKAGE` | Latest N versions per package (retention). | 3 |
| `REPO_MIRROR_NO_DEFAULT_UPSTREAMS` | Disable default upstreams when no config (set to `1` or `true`). | — |
| `REPO_MIRROR_ENABLE_API` | Enable REST API (`/api/v1` publish, health). Set to `1` or `true`. **Off by default.** Any client that can reach the API can publish; secure it externally. | — |

Full reference: [docs/operations.md](docs/operations.md).

### No config: default upstreams

If you **don’t provide a config file**, repo-man uses built-in **default upstreams** so clients can use the mirror immediately with minimal setup:

| Path prefix | Format | Use in clients |
|-------------|--------|----------------|
| `/ubuntu` | APT | `deb http://HOST:8080/ubuntu noble main` (jammy, noble, noble-updates, noble-security) |
| `/debian` | APT | `deb http://HOST:8080/debian bookworm main` (bookworm, bookworm-updates) |
| `/rocky9` | RPM | `baseurl=http://HOST:8080/rocky9` (Rocky Linux 9 BaseOS) |

To **disable** default upstreams (e.g. you only want upstreams from your own config): set **`REPO_MIRROR_NO_DEFAULT_UPSTREAMS=1`**, pass **`--no-default-upstreams`** to `repo-man serve`, or create a config file with **`disable_default_upstreams: true`**. Providing a config file that defines any upstreams also disables defaults (only your configured upstreams are used).

## Example

With **no config**, just run the server; default upstreams (Ubuntu, Debian, Rocky 9, Alpine) are used and clients can point at the path prefixes above.

With **Docker**, run cache/publish via `docker exec repo-man repo-man <command> ...`; the server is already up. From **source**:

```bash
# Optional: add more upstreams or override defaults
repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ --format apt --layout classic --path-prefix /ubuntu --suites noble --components main --archs amd64
repo-man publish add --path-prefix /local/ ./pkg.deb
repo-man serve --port 8080
# With publish API enabled (for CI or remote publish):
repo-man serve --port 8080 --enable-api
# Publish via API (any client that can reach the API can publish; secure it externally):
curl -X POST -F path_prefix=/local/ -F format=apt -F suite=stable -F component=main -F arch=amd64 -F "packages=@pkg.deb" http://localhost:8080/api/v1/publish
```

Metrics are exposed on the same port: `GET /metrics` (Prometheus).

## Docker integration test

Run the service in Compose, then a client container that uses it to install packages (pull-through from upstream repos). The integration test uses Ubuntu and the APT format:

```bash
docker compose -f tests/docker/compose.integration.yaml up -d
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client
```

See [tests/docker/README.md](tests/docker/README.md) for details.

## Support

**Only the latest release is supported.** No patches or backports are made to older versions.

The latest image is always available on Docker Hub as `awesomeit/repo-man:latest`.

### SBOM

To generate a Software Bill of Materials for the current image:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  anchore/syft:latest awesomeit/repo-man
```
