# Docker-based integration test

Runs repo-man in Docker Compose, seeds the Ubuntu (jammy, noble, noble-updates, noble-security) and GitLab CE upstreams, then uses client containers to verify the mirror and demonstrate cache pruning. Verifies pull-through cache (metadata and .deb fetched from upstream on first request, then served from cache).

## Prerequisites

- Docker and Docker Compose
- Run from project root

## Run

```bash
# From project root
docker compose -f tests/docker/compose.integration.yaml up -d
# Cache 2 vim versions from same repo (noble main + noble-updates); automatic prune drops 1 (CACHE_VERSIONS_PER_PACKAGE=1)
docker compose -f tests/docker/compose.integration.yaml run --rm vim-three-versions

# See automatic pruning in the mirror logs (look for "Auto-pruned" and "keep 1 version(s) per package")
docker compose -f tests/docker/compose.integration.yaml logs repo-man

# Optional: run cache prune manually (may remove 0 if auto-prune already ran)
docker compose -f tests/docker/compose.integration.yaml run --rm prune-demo
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client
docker compose -f tests/docker/compose.integration.yaml run --rm ubuntu-client-24
```

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

1. Points APT at `http://repo-man:8080/ubuntu` (jammy main) and `http://repo-man:8080/gitlab-ce` (jammy main)
2. Runs `apt-get update` (metadata is pulled through from archive.ubuntu.com and packages.gitlab.com)
3. Runs `apt-get install -y vim`, then `vim --version`
4. Runs `apt-get install -y gitlab-ce`, then `gitlab-ctl status` (or true)

**ubuntu-client-24** (Ubuntu 24.04 / noble):

1. Points APT at `http://repo-man:8080/ubuntu` (noble main)
2. Runs `apt-get update`, then `apt-get install -y vim` and `vim --version`

Exit code 0 from each client means the mirror served that suite successfully.

## Cleanup

```bash
docker compose -f tests/docker/compose.integration.yaml down
```

Optionally remove the volume to clear cached packages:

```bash
docker compose -f tests/docker/compose.integration.yaml down -v
```
