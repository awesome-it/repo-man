# Docker-based integration test

Runs repo-man in Docker Compose with **APT**, **RPM**, and **Alpine** upstreams. Seeds Ubuntu (jammy, noble, noble-updates, noble-security), Rocky 9 BaseOS (RPM), and Alpine 3.19 main. Client containers verify the mirror for each format and demonstrate cache pruning. Verifies pull-through cache (metadata and packages fetched from upstream on first request, then served from cache).

## Prerequisites

- Docker and Docker Compose
- Run from project root

## Run

```bash
# From project root: start all services (repo-man + APT/RPM/Alpine upstreams)
docker compose -f tests/docker/compose.integration.yaml up -d

# Cache 2 vim versions from same repo (noble main + noble-updates); automatic prune drops 1 (CACHE_VERSIONS_PER_PACKAGE=1)
docker compose -f tests/docker/compose.integration.yaml run --rm vim-three-versions

# See automatic pruning in the mirror logs (look for "Auto-pruned" and "keep 1 version(s) per package")
docker compose -f tests/docker/compose.integration.yaml logs repo-man

# Optional: run cache prune manually (may remove 0 if auto-prune already ran)
docker compose -f tests/docker/compose.integration.yaml run --rm prune-demo

# APT clients (Ubuntu)
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client-24

# RPM client (Rocky Linux 9) — installs a package from repo-man mirror of Rocky 9 BaseOS
docker compose -f tests/docker/compose.integration.yaml run --rm rpm-client

# Build → publish → install: build a .deb, publish via API, install from local repo
docker compose -f tests/docker/compose.integration.yaml run --rm build-publish-install-client
```

### APT-only (faster)

To run only APT-related clients and skip RPM, use the same compose file but run only the APT services: `ubuntu-client`, `ubuntu-client-24`, `vim-three-versions`, `prune-demo`. The repo-man service still adds RPM and Alpine upstreams to config; to avoid that you would need a separate compose file or override the entrypoint (e.g. `compose.override.yaml` with a slimmer command).

**vim-three-versions** (simulate host with vim that does one update after another):

1. Points APT at `http://repo-man:8080/ubuntu` for noble, noble-updates, noble-security (main)
2. Installs vim (older version from noble main); mirror caches it
3. Runs `apt-get update` then installs vim again (newer version from noble-updates); mirror caches the second .deb
4. Mimics a host that has vim installed and then runs an update (e.g. security update), so two vim versions are cached from the same repo  
5. The **serve process automatically prunes** after the second cache write: it keeps only 1 version per package, so the older vim .deb is removed. Check `docker compose -f tests/docker/compose.integration.yaml logs repo-man` for a line like: `Auto-pruned 1 cached package(s) (keep 1 version(s) per package)`.

**prune-demo** (optional):

1. Runs `repo-man cache prune` with the same repo volume
2. With automatic pruning, the extra version may already have been removed by the serve process; this step confirms the same behavior on demand

**ubuntu-client** (Ubuntu 22.04 / jammy):

1. Points APT at `http://repo-man:8080/ubuntu` (jammy main)
2. Runs `apt-get update` (metadata is pulled through from archive.ubuntu.com via repo-man)
3. Runs `apt-get install -y vim curl`, then `vim --version` and `curl --version`

**ubuntu-client-24** (Ubuntu 24.04 / noble):

1. Points APT at `http://repo-man:8080/ubuntu` (noble main)
2. Runs `apt-get update`, then `apt-get install -y vim` and `vim --version`

**rpm-client** (Rocky Linux 9):

1. Configures a YUM repo pointing at `http://repo-man:8080/rocky9` (mirror of Rocky 9 BaseOS)
2. Runs `dnf install -y tar` (pull-through from upstream, then served from cache)
3. Exit 0 means the RPM mirror worked

**alpine-client** (Alpine 3.19):

1. Adds `http://repo-man:8080/alpine319` to APK repositories (mirror of Alpine 3.19 main)
2. Runs `apk add --no-cache musl` (pull-through from upstream)
3. Exit 0 means the Alpine mirror worked

**build-publish-install** (build → publish → install):

1. **build-publish-install-builder**: Uses repo-man as APT source (noble main universe), installs `equivs` and `curl`, builds a trivial package `hello-repoman` with equivs-build, then publishes it via `POST /api/v1/publish` (repo-man must be started with `--enable-api`).
2. **build-publish-install-client**: Depends on the builder; uses only `deb http://repo-man:8080/local stable main`, runs `apt-get update` and `apt-get install -y hello-repoman`, verifies the package is installed.
3. Exit 0 means the full build → publish → install flow worked.

Exit code 0 from each client means the mirror served that format successfully.

## Cleanup

```bash
docker compose -f tests/docker/compose.integration.yaml down
```

Optionally remove the volume to clear cached packages:

```bash
docker compose -f tests/docker/compose.integration.yaml down -v
```
