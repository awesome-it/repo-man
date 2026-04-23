# Deployment examples

Concrete setups for using repo-man as a package cache and publishing server in offices, datacenters, Kubernetes, and Compose-based build pipelines.

---

## 1. Office or datacenter package cache and publishing

**Goal:** One shared repo-man instance for the LAN: pull-through cache of upstream distros (e.g. Ubuntu, Debian) plus an internal repo for your own .deb packages. Desktops and servers point APT at the cache to reduce internet traffic and speed up installs.

### Layout

- **Single server** (VM or physical) runs repo-man.
- **Upstreams:** e.g. Ubuntu jammy/noble, Debian bookworm; optional Kubernetes or vendor APT repos.
- **Local repo:** Publish internal packages under a path prefix (e.g. `/local/`) for deployment across the office/datacenter.
- **Clients:** Configure `sources.list` / `sources.list.d/` to use `http://repo-man.example.com:8080/ubuntu`, `http://repo-man.example.com:8080/local`, etc.

### Config example

Save as `config.yaml` in your repo data directory (e.g. `/var/lib/repo-man/config.yaml`):

```yaml
upstreams:
  - name: ubuntu
    url: https://archive.ubuntu.com/ubuntu/
    meta_release_base_url: https://changelogs.ubuntu.com/
    layout: classic
    path_prefix: /ubuntu
    suites: [jammy, jammy-updates, jammy-security, noble, noble-updates, noble-security]
    components: [main, universe]
    archs: [amd64]
  # Password protected repos liek ubuntu-pro
  # Note: Client access is not passwort protected anymore!
  - name: ubuntu-esm-apps
    url: https://esm.ubuntu.com/apps/ubuntu
    base_url: https://esm.ubuntu.com/apps/ubuntu
    layout: classic
    path_prefix: /ubuntu_esm_apps
    suites:
    - jammy-apps-security
    - jammy-apps-updates
    components:
    - main
    archs:
    - amd64
    # Yes this is correct for ubuntu pro...
    auth:
      type: basic
      username: bearer
      password: <your login token here>
  - name: debian
    url: https://deb.debian.org/debian/
    layout: classic
    path_prefix: /debian
    suites: [bookworm, bookworm-updates]
    components: [main, contrib]
    archs: [amd64]

# Cap cache size; published packages under /local/ are never pruned
disk:
  high_watermark_bytes: 10737418240   # 10 GiB
```

### Run

```bash
# One-time: create repo root and config
export REPO_MIRROR_REPO_ROOT=/var/lib/repo-man

# Run server (systemd, Docker, or foreground)
repo-man serve --bind 0.0.0.0 --port 8080
```

### Client configuration (APT)

On each client (Ubuntu/Debian):

```bash
# Replace repo-man.example.com with your server hostname or IP
echo 'deb http://repo-man.example.com:8080/ubuntu noble main universe' > /etc/apt/sources.list.d/repo-man-ubuntu.list
echo 'deb http://repo-man.example.com:8080/local ./' >> /etc/apt/sources.list.d/repo-man-local.list
apt-get update
apt-get install <packages>
```

Ubuntu Pro / ESM Infra via repo-man (example):

```bash
echo 'deb http://repo-man.example.com:8080/ubuntu-esm-infra jammy-infra-security main' > /etc/apt/sources.list.d/repo-man-esm-infra.list
echo 'deb http://repo-man.example.com:8080/ubuntu-esm-infra jammy-infra-updates main' >> /etc/apt/sources.list.d/repo-man-esm-infra.list
apt-get update
```

For HTTPS or signed repos, put the mirror’s certificate and use `deb https://...` as needed; repo-man serves HTTP by default.

### Optional: disk and retention

- Set `REPO_MIRROR_DISK_HIGH_WATERMARK_BYTES` (or `disk.high_watermark_bytes` in config) so the cache is pruned when over the limit; published content under `/local/` is kept.
- Use `CACHE_VERSIONS_PER_PACKAGE=3` (default) so only the latest N versions per package are kept; adjust for space vs. history.

---

## 2. Kubernetes per-node daemonset

**Goal:** Run one repo-man instance per node so that workloads on a node (e.g. CI jobs, build pods) use a **local** package cache on that node. Reduces cross-node traffic and speeds up repeated `apt-get install` in pipelines.

### Pattern

- **DaemonSet:** One pod per node.
- **hostPath volume:** Cache and config live on the node’s disk so they persist across pod restarts and are local to the node.
- **hostNetwork:** The pod listens on the node’s network so that other pods on the same node can reach it at the **node IP** (or, if they use hostNetwork too, at `localhost:8080`). No ClusterIP load-balancing: each node has its own cache.

### DaemonSet example

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: repo-man
  namespace: default
spec:
  selector:
    matchLabels:
      app: repo-man
  template:
    metadata:
      labels:
        app: repo-man
    spec:
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      containers:
        - name: repo-man
          image: awesomeit/repo-man:latest
          args:
            - serve
            - --bind
            - "0.0.0.0"
            - --port
            - "8080"
          env:
            - name: REPO_MIRROR_REPO_ROOT
              value: /data
            - name: CACHE_VERSIONS_PER_PACKAGE
              value: "2"
          ports:
            - containerPort: 8080
              hostPort: 8080
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          hostPath:
            path: /var/lib/repo-man
            type: DirectoryOrCreate
```

- **hostNetwork: true** + **hostPort: 8080** so the service is reachable at `<node-ip>:8080`.
- **hostPath:** `/var/lib/repo-man` on each node holds cache and optional `config.yaml`. Seed config once (see below) or bake it into an init image.

### Using the cache from pods on the same node

Workloads need to call the **repo-man on their node**, not a random node. Use the **node IP** from the downward API:

```yaml
env:
  - name: NODE_IP
    valueFrom:
      fieldRef:
        fieldPath: status.hostIP
  - name: APT_PROXY
    value: "http://$(NODE_IP):8080"
```

Then in your job or build script:

```bash
# Use repo-man on this node as APT proxy
echo "deb [allow-insecure=yes] http://${NODE_IP}:8080/ubuntu noble main" > /etc/apt/sources.list
apt-get update -o Acquire::AllowInsecureRepositories=true
apt-get install -y vim build-essential
```

### Seeding config on the node

Either:

- **Bake config into the image:** Add a default `config.yaml` in the image at `/data/config.yaml` (e.g. in a custom Dockerfile that copies config and uses an entrypoint that runs `repo-man cache add-upstream ...` if missing, then `exec repo-man serve ...`), or
- **Init container or one-off Job:** Run a Job (with the same hostPath and nodeSelector so it runs on each node once, or run once per node) that writes `config.yaml` and optionally runs `repo-man cache add-upstream ...` to seed upstreams. After that, the DaemonSet pods will use the existing config and cache.

---

## 3. Compose setup for faster installs in build pipelines

**Goal:** In a Compose-based build or test pipeline, many services run `apt-get update && apt-get install ...`. Use a **shared repo-man service** so the first run pulls from the internet and caches, and later services (and later pipeline runs) get packages from the cache. Speeds up Compose “build” and test steps.

### Zero-modification Docker builds via DNS override

If your build containers are based on Debian/Ubuntu and you want to avoid modifying Dockerfiles or container commands, run repo-man + CoreDNS on the build host and route APT hostnames to repo-man by DNS.

1. Run the following stack on the build host:

```yaml
services:
  repo-cache:
    image: registry.awesome-it.de/upstream-dockerhub/awesomeit/repo-man:latest
    ports:
      - "127.0.0.1:80:8080"
    restart: unless-stopped
    dns:
      - 1.1.1.1

  coredns:
    image: coredns/coredns:1.13.1
    command: ["-conf", "/etc/coredns/Corefile"]
    ports:
      - "127.0.0.1:53:53/udp"
      - "127.0.0.1:53:53/tcp"
    configs:
      - source: coredns_corefile
        target: /etc/coredns/Corefile
    restart: unless-stopped

configs:
  coredns_corefile:
    content: |
      .:53 {
          log
          errors
          cache 300

          hosts {
              172.17.0.1 archive.ubuntu.com security.ubuntu.com
              fallthrough
          }

          # Use your standard upstream resolver(s) here.
          forward . 1.1.1.1 8.8.8.8
      }
```

2. Point the Docker daemon on the build host to CoreDNS:

```json
{
  "dns": ["127.0.0.1"]
}
```

Then restart Docker. New containers will resolve `archive.ubuntu.com` / `security.ubuntu.com` to `172.17.0.1` (your local Docker host), which serves repo-man on port `80`.

Notes:
- Find the correct host gateway IP from a test container if needed:

```bash
docker run --rm alpine sh -c "ip route | awk '/default/ {print \$3}'"
```

- If your environment uses a different gateway address, replace `172.17.0.1` in the `hosts` block.
- Keep `forward . ...` pointed at a shared/corporate upstream DNS resolver so all non-overridden domains continue to resolve normally.
- If port `53` is already used on the host (for example by `systemd-resolved`), run CoreDNS on another address or free port `53` first.

### Layout

- **One repo-man service** in the same Compose project, with a **named volume** (or bind mount) for cache so data persists across `compose up` runs.
- **Build/test services** use the repo-man service as their APT source (e.g. `http://repo-man:8080/ubuntu`).
- All services share the same network so they reach repo-man by service name.

### Compose example

```yaml
services:
  repo-man:
    image: awesomeit/repo-man:latest
    environment:
      REPO_MIRROR_REPO_ROOT: /data
      CACHE_VERSIONS_PER_PACKAGE: "3"
    volumes:
      - repo_cache:/data
    command: ["serve", "--bind", "0.0.0.0", "--port", "8080"]
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/metrics')"]
      interval: 5s
      timeout: 3s
      retries: 3
      start_period: 10s

  builder:
    image: ubuntu:24.04
    depends_on:
      repo-man:
        condition: service_healthy
    environment:
      DEBIAN_FRONTEND: noninteractive
    command:
      - bash
      - -c
      - |
        echo 'deb [allow-insecure=yes] http://repo-man:8080/ubuntu noble main universe' > /etc/apt/sources.list
        apt-get update -o Acquire::AllowInsecureRepositories=true
        apt-get install -y build-essential cmake git
        # ... your build steps ...

  tester:
    image: ubuntu:24.04
    depends_on:
      repo-man:
        condition: service_healthy
    environment:
      DEBIAN_FRONTEND: noninteractive
    command:
      - bash
      - -c
      - |
        echo 'deb [allow-insecure=yes] http://repo-man:8080/ubuntu noble main' > /etc/apt/sources.list
        apt-get update -o Acquire::AllowInsecureRepositories=true
        apt-get install -y python3 pytest
        # ... your test steps ...
```

- **repo-man** uses a named volume `repo_cache` so the cache survives `compose down` (use `compose down -v` only when you want to clear it).
- **builder** and **tester** wait for repo-man to be healthy, then point APT at `http://repo-man:8080/ubuntu`. The first run fills the cache; subsequent runs and other services hit the cache.

### Optional: seed upstreams at startup

If you want upstreams to exist before any client request, use an entrypoint that seeds then serves:

```yaml
  repo-man:
    image: awesomeit/repo-man:latest
    environment:
      REPO_MIRROR_REPO_ROOT: /data
      CACHE_VERSIONS_PER_PACKAGE: "3"
    volumes:
      - repo_cache:/data
    entrypoint: ["sh", "-c"]
    command:
      - |
        if [ ! -f /data/config.yaml ]; then
          repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ \
            --layout classic --path-prefix /ubuntu \
            --suites noble,noble-updates,noble-security --components main,universe --archs amd64
        fi
        exec repo-man serve --bind 0.0.0.0 --port 8080
    # ... healthcheck as above ...
```

### Speeding up repeated pipeline runs

- Keep the **same Compose project and volume** between pipeline runs so the cache is reused (e.g. same runner or same volume backend).
- Use a **long-lived repo-man** (e.g. a dedicated Compose stack or a single service that stays up) and point all build/test jobs at it so cache warms once and is shared across jobs.

---

## 4. Publish from CI

**Goal:** Build packages in CI (e.g. .deb, .rpm, .apk) and publish them to repo-man so that other jobs or machines can install them from the same server. Use the **publish API** so CI only needs HTTP access (no `docker exec` or SSH).

**Prerequisites:** The REST API must be enabled: start repo-man with `--enable-api`, or set `REPO_MIRROR_ENABLE_API=1`, or set `api.enable: true` in config. **Any client that can reach the API can publish;** repo-man does not authenticate API requests. Secure the API externally (e.g. reverse proxy with auth, network policy so only CI can reach the API, or run repo-man in a private network).

**Example (curl):** After building `my-pkg_1.0_amd64.deb`, publish to path prefix `/local/`:

```bash
curl -X POST \
  -F path_prefix=/local/ \
  -F format=apt \
  -F suite=stable \
  -F component=main \
  -F arch=amd64 \
  -F "packages=@my-pkg_1.0_amd64.deb" \
  http://repo-man.example.com:8080/api/v1/publish
```

Success response: `{"published": 1, "path_prefix": "/local/", "changed": true}`. Clients can then use `deb http://repo-man.example.com:8080/local ./` in their sources.

---

## See also

- [Operations](operations.md) — config reference, metrics, disk watermark.
- [APT repository types](apt-repo-types.md) — upstream layouts (classic, single-stream) and path prefixes.
- [Architecture](architecture.md) — components and data flow.
