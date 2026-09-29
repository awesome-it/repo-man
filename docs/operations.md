# Operations

Running repo-man in production: config reference, Prometheus metrics, and deployment. The config examples below are for the included APT format; other formats would define their own upstream fields.

## Config reference

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REPO_MIRROR_REPO_ROOT` | Root directory for repo data (cache + local). | `./repo_data` |
| `REPO_MIRROR_CONFIG` | Path to config file (YAML/TOML). | None (optional) |
| `CACHE_VERSIONS_PER_PACKAGE` | Keep latest N versions per package; applied automatically by the serve process after each cache write (and by `cache prune`). | 3 |
| `REPO_MIRROR_METADATA_TTL_SECONDS` | Metadata cache TTL in seconds; cached metadata (Release, Packages.gz, etc.) is re-fetched from upstream when older than this. | 1800 (30 minutes) |
| `REPO_MIRROR_DISK_HIGH_WATERMARK_BYTES` | Repo disk high watermark; when exceeded, cache (not published) is pruned. Set to `off`, `none`, or `disabled` to disable. | 10 GiB |
| `REPO_MIRROR_PACKAGE_HASH_STORE` | Backend for package hash storage: `local` (SQLite under repo root) or `redis`. Used to detect when a cached package has changed on the remote; if so, the cache entry is dropped and a counter is incremented. | `local` |
| `REPO_MIRROR_REDIS_URL` | Redis URL when `REPO_MIRROR_PACKAGE_HASH_STORE=redis`. | `redis://localhost:6379/0` |
| `REPO_MIRROR_NO_DEFAULT_UPSTREAMS` | If set to `1`, `true`, or `yes`, disables built-in default upstreams when no config file (or empty upstreams) is present. | — |
| `REPO_MIRROR_ENABLE_API` | If set to `1`, `true`, or `yes`, enables the REST API (`/api/v1` and legacy `POST /api/publish`). **Off by default.** See [Publish API](#publish-api) below. | — |
| `REPO_MIRROR_PUBLIC_BASE_URL` | Public base URL for client-facing mirror URLs in `repo-man status` (e.g. `https://repo.example.com`). | — |
| `REPO_MIRROR_HEALTH_CHECK_INTERVAL_SECONDS` | Interval between upstream health probes while `serve` is running (metadata + sample package). `0` disables the loop after the initial probe. | 300 |

### Default upstreams (no config)

When **no config file exists** (or the config file has no `upstreams`), repo-man uses **built-in default upstreams** so clients can use the mirror with minimal setup:

- **APT** — `/ubuntu` (Ubuntu jammy, jammy-updates, jammy-security, noble, noble-updates, noble-security), `/debian` (Debian bookworm, bookworm-updates)
- **RPM** — `/rocky9` (Rocky Linux 9 BaseOS x86_64)
- **Alpine** — `/alpine` (Alpine 3.19 main)

To **disable** default upstreams (e.g. you want to define only your own upstreams):

1. **Config file** — Set `disable_default_upstreams: true` in your YAML/TOML, or define any `upstreams` (then only those are used).
2. **Environment** — Set `REPO_MIRROR_NO_DEFAULT_UPSTREAMS=1` (or `true` / `yes`).
3. **CLI** — Run `repo-man serve --no-default-upstreams`.

### Config file shape (YAML example, APT upstreams)

```yaml
# Set to true to disable built-in default upstreams when you want only the upstreams listed here
# disable_default_upstreams: false

upstreams:
  - name: ubuntu
    url: https://archive.ubuntu.com/ubuntu/
    # Optional: where meta-release metadata is fetched from (used by do-release-upgrade)
    meta_release_base_url: https://changelogs.ubuntu.com/
    layout: classic
    path_prefix: /ubuntu
    suites: [jammy]
    components: [main, universe]
    archs: [amd64]
    # Ubuntu/Debian/Docker: one shared path_prefix (default is false; explicit for clarity).
    split_suites: false
  - name: k8s-v1.34
    url: https://pkgs.k8s.io/core:/stable:/v1.34/deb/
    layout: single-stream
    path_prefix: /k8s/v1.34
  - name: ubuntu-esm-infra
    url: https://esm.ubuntu.com/infra/ubuntu/
    layout: classic
    path_prefix: /ubuntu-esm-infra
    suites: [jammy-infra-security, jammy-infra-updates]
    components: [main]
    archs: [amd64]
    split_suites: false
    # Optional upstream auth (for protected upstreams such as ESM):
    auth:
      type: bearer
      token_env: REPO_MIRROR_ESM_TOKEN
  # Vendor classic repos that reuse pool Filenames across suites (e.g. GitLab):
  # set split_suites: true so each suite gets /GitLab/<suite>.
  # - name: GitLab
  #   url: https://packages.gitlab.com/gitlab/gitlab-ce/ubuntu/
  #   layout: classic
  #   path_prefix: /GitLab
  #   suites: [focal, jammy, noble]
  #   components: [main]
  #   archs: [amd64]
  #   split_suites: true

# Optional: metadata cache TTL in seconds; cached metadata is re-fetched when older than this (default 1800)
# metadata_ttl_seconds: 1800

# Optional: public base URL for client lines shown by `repo-man status`
# public_base_url: https://repo.example.com

# Optional: how often serve probes each upstream (metadata + sample package); default 300
# health_check_interval_seconds: 300

# Optional: package hash store: "local" (SQLite at repo_root/hash_store.db) or "redis"
# package_hash_store: local
# redis_url: redis://localhost:6379/0

# Optional: when repo size exceeds this (bytes), cache is pruned until under; published packages are kept
disk:
  high_watermark_bytes: 10737418240   # 10 GiB

# Optional: enable the REST API (/api/v1, legacy POST /api/publish). Off by default.
# api:
#   enable: true
```

### Suite splitting (`split_suites`)

Classic APT upstreams with **two or more suites** share one `path_prefix` by default. Set `split_suites: true` to expand at load time into one logical upstream per suite (`path_prefix/<suite>`, cache name `name-suite`).

That isolates the shared `pool/` cache so suites that advertise the same `Filename` with different blobs (common on some vendor repos such as GitLab) cannot overwrite each other. Ubuntu, Debian, and Docker keep the default (`false`) so clients use a single `/ubuntu`, `/debian`, or `/docker` prefix.

Example after expansion for GitLab with `split_suites: true` and suites `jammy` and `noble`:

```yaml
# becomes effectively:
# path_prefix: /GitLab/jammy  (name: GitLab-jammy, suites: [jammy])
# path_prefix: /GitLab/noble  (name: GitLab-noble, suites: [noble])
```

CLI: `repo-man cache add-upstream ... --split-suites` / `--no-split-suites` (default when omitted: no split).

- Serve: `/GitLab/jammy/...` and `/GitLab/noble/...`
- Client: `deb http://mirror/GitLab/jammy jammy main`

### Package pull-through (stream-through)

Pool package misses (`.deb` / `.rpm` / `.apk`) are **streamed through**: the ASGI server sends upstream bytes to the client as they arrive while teeing them to `cache/<upstream>/….partial`, then atomically renaming to the final key. Concurrent clients for the same key attach to one in-flight fetch (partial replay + live fan-out). Client disconnect does not cancel the upstream fill. Metadata (Release, Packages, repodata, APKINDEX, etc.) remains store-then-serve.

### Upstream authentication

For protected upstreams, define `auth` under each upstream in config:

- **Bearer token** (recommended for ESM/API token flows):
  - `auth.type: bearer`
  - `auth.token_env: <ENV_VAR_NAME>` or `auth.token: <TOKEN>`
- **Basic auth**:
  - `auth.type: basic`
  - `auth.username_env`, `auth.password_env` or `auth.username`/`auth.password`

Using `*_env` avoids storing secrets in config files.

If `REPO_MIRROR_CONFIG` is not set, the CLI may default to `<REPO_MIRROR_REPO_ROOT>/config.yaml` when saving upstreams.

### do-release-upgrade via mirror

To keep LTS upgrades on the same mirror host, point Ubuntu's release upgrader metadata to repo-man:

```bash
# Use LTS-to-LTS prompts
sudo sed -i 's/^Prompt=.*/Prompt=lts/' /etc/update-manager/release-upgrades

# Fetch release metadata through repo-man (replace HOST:8080)
sudo sed -i 's#^URI=.*#URI=http://HOST:8080/ubuntu/meta-release#' /etc/update-manager/meta-release
sudo sed -i 's#^URI_LTS=.*#URI_LTS=http://HOST:8080/ubuntu/meta-release-lts#' /etc/update-manager/meta-release
```

Then run `sudo do-release-upgrade`.

When serving `meta-release` / `meta-release-lts`, repo-man rewrites Ubuntu archive URLs
(`archive.ubuntu.com`, `*.archive.ubuntu.com`, `security.ubuntu.com`, `old-releases.ubuntu.com`)
in the body to the request's public origin (from `Host` / `X-Forwarded-Host` and
`X-Forwarded-Proto`) plus the upstream `path_prefix`. That way `Release-File` and
`UpgradeTool` downloads also go through the mirror. Links to `changelogs.ubuntu.com`
(e.g. EOL release notes) are left unchanged.

Only **GET** and **scoped HEAD** are served for repo paths: HEAD is accepted for `do-release-upgrade` metadata (paths under the dist-upgrader tree and for `meta-release` / `meta-release-lts` at the end of the URL); other HEAD requests return 404.

## Publish API

When enabled (via `REPO_MIRROR_ENABLE_API=1`, config `api.enable: true`, or `repo-man serve --enable-api`), the server exposes the REST API and accepts publish requests. **The API is off by default.**

- **Preferred:** **`POST /api/v1/publish`** — versioned endpoint; same form fields and behaviour.
- **Legacy:** **`POST /api/publish`** — deprecated; use `POST /api/v1/publish` instead. Still supported for compatibility.

**Health check:** **`GET /api/v1/health`** returns `{"status": "ok"}` when the API is enabled.

**Authentication:** Repo-man does not authenticate API requests. **Any connection that can reach the API is allowed to publish.** Securing the API is the deployer’s responsibility: use a reverse proxy with authentication, mTLS, network policies so only trusted clients can reach the API, or do not enable/expose the API.

**Request:** `Content-Type: multipart/form-data`. Required form fields:

- **path_prefix** (required) — Path prefix for the local repo (e.g. `/local/`).
- **format** — `apt`, `rpm`, or `alpine`. Default `apt`.
- **packages** or **files** — One or more package files (e.g. `.deb`, `.rpm`, `.apk`).

Format-specific fields (optional):

- **APT:** `suite` (default `stable`), `component` (default `main`), `arch` (default `amd64`).
- **RPM:** `arch` (default `amd64`).
- **Alpine:** `branch` (default `main`).

**Response:** JSON. Success: `200` with `{"published": N, "path_prefix": "...", "changed": true|false}`. Error: `400` or `500` with `{"error": "..."}`.

**Example (APT, curl):**

```bash
curl -X POST \
  -F path_prefix=/local/ \
  -F format=apt \
  -F suite=stable \
  -F component=main \
  -F arch=amd64 \
  -F "packages=@my-package_1.0_amd64.deb" \
  http://repo-man.example.com:8080/api/v1/publish
```

**Example (RPM, curl):**

```bash
curl -X POST \
  -F path_prefix=/local/ \
  -F format=rpm \
  -F arch=x86_64 \
  -F "packages=@my-package-1.0-1.x86_64.rpm" \
  http://repo-man.example.com:8080/api/v1/publish
```

## Disk watermark

The disk high watermark defaults to **10 GiB**; override with `REPO_MIRROR_DISK_HIGH_WATERMARK_BYTES` or `disk.high_watermark_bytes` in config. To disable size-based pruning, set the env to `off`, `none`, or `disabled`, or set `disk.high_watermark_bytes: null` in config.

**Automatic pruning (serve process)**  
After each cache write (pull-through of a package or metadata), the serve process:

1. **Version trim**: Keeps only the latest `CACHE_VERSIONS_PER_PACKAGE` versions per package per upstream (older versions are removed).
2. **Watermark** (if set): If repo usage is above the disk high watermark, frees cache until under (evicting by oldest last-served when a package hash store is configured).

So you do not need to run `cache prune` on a schedule for normal operation; it is still available for one-off or scripted runs.

**On demand**  
When you run `repo-man cache prune` (or when the serve process runs the watermark step above), the logic is:

1. Measure total repo size (cache + published).
2. If size is above the watermark, free space by pruning **only** pull-through cache (`cache/<upstream>/`). Published packages (e.g. under `local/`) are never removed.
3. **When a package hash store is configured** (local or redis): packages are evicted in **oldest last-served first** order (the KV store records when each cached package was last served; least recently used are dropped until under the watermark).
4. **When no hash store is configured**: first keep 1 version per package per upstream; if still over, remove all cached packages until under the watermark.

Use this to cap disk usage and keep only recent package versions while guaranteeing that published content is kept.

## Prometheus metrics

Endpoint: **`GET /metrics`** on the same HTTP server as the repo (same port).

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `repo_man_http_requests_total` | Counter | method, path_prefix, status | HTTP request count. |
| `repo_man_http_request_duration_seconds` | Histogram | path_prefix | Request duration. |
| `repo_man_cache_requests_total` | Counter | result (hit/miss) | Cache lookups. |
| `repo_man_cache_upstream_fetches_total` | Counter | upstream | Upstream package fetches. |
| `repo_man_cache_upstream_fetch_duration_seconds` | Histogram | upstream | Fetch duration. |
| `repo_man_cache_upstream_fetch_errors_total` | Counter | upstream | Fetch errors. |
| `repo_man_packages_pulled_from_upstream_total` | Counter | upstream | Packages fetched from upstream and stored (pull-through). |
| `repo_man_upstream_last_access_timestamp_seconds` | Gauge | upstream | Unix timestamp of last fetch from this upstream (metadata or package). |
| `repo_man_upstream_up` | Gauge | upstream | `1` if the last health probe fetched metadata and a sample package successfully, else `0`. |
| `repo_man_upstream_last_check_timestamp_seconds` | Gauge | upstream | Unix timestamp when the last upstream health probe finished. |
| `repo_man_cache_package_hash_mismatch_total` | Counter | upstream | Cached packages dropped because the remote hash changed (re-fetched on next request). |
| `repo_man_packages_served_total` | Counter | path_prefix | Packages served to clients. |
| `repo_man_client_packages_served_total` | Counter | client | Packages served per client (client = IP or hostname from reverse DNS). |
| `repo_man_client_last_served_timestamp_seconds` | Gauge | client | Unix timestamp when last package was served to each client. |
| `repo_man_metadata_requests_total` | Counter | type, result | Metadata requests. |
| `repo_man_prune_runs_total` | Counter | - | Prune job runs. |
| `repo_man_prune_packages_removed_total` | Counter | upstream | Packages removed by prune. |
| `repo_man_prune_duration_seconds` | Histogram | - | Prune duration. |
| `repo_man_prune_errors_total` | Counter | - | Prune errors. |
| `repo_man_publish_uploads_total` | Counter | path_prefix | Packages published. |
| `repo_man_publish_errors_total` | Counter | path_prefix | Publish errors. |
| `repo_man_publish_duration_seconds` | Histogram | path_prefix | Publish duration. |
| `repo_man_storage_operations_total` | Counter | operation, backend | Storage ops. |
| `repo_man_storage_operation_duration_seconds` | Histogram | operation, backend | Storage op duration. |
| `repo_man_storage_errors_total` | Counter | operation, backend | Storage errors. |

Example Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: repo-man
    static_configs:
      - targets: ['repo-man:8080']
    metrics_path: /metrics
```

## Container and volume layout

- **Dockerfile**: Multi-stage build with uv; runtime image runs `repo-man serve` by default. Exposes port 8080. Volume mount repo data at `/data` (or set `REPO_MIRROR_REPO_ROOT`).
- **Compose**: `compose.yaml` runs the app with `./repo_data` mounted at `/data`. Metrics at `http://localhost:8080/metrics`.

Run with Docker:

```bash
docker build -t repo-man .
docker run -p 8080:8080 -v $(pwd)/repo_data:/data repo-man
```

Run with Compose:

```bash
docker compose up -d
```

## Health checks

**Process liveness:** use `GET /metrics` (200) or `GET /api/v1/health` when the API is enabled.

**Upstream reachability:** while `serve` runs, repo-man periodically probes each configured upstream (metadata + a sample package) and sets `repo_man_upstream_up{upstream="..."}` to `1` or `0`. Results are also written to `<repo_root>/upstream_status.json`. Use `repo-man status` to print last-known state (or `repo-man status --check` to probe immediately). See [monitoring.md](monitoring.md#upstream-health-probes-preferred).
