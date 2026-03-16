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
    layout: classic
    path_prefix: /ubuntu
    suites: [jammy, noble, noble-updates, noble-security]
    components: [main, universe]
    archs: [amd64]
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

### Seed and run

```bash
# One-time: create repo root and config
export REPO_MIRROR_REPO_ROOT=/var/lib/repo-man
mkdir -p "$REPO_MIRROR_REPO_ROOT"
# ... copy or link config.yaml into $REPO_MIRROR_REPO_ROOT/config.yaml ...

# Optional: pre-seed upstreams via CLI (or let them be created on first request)
repo-man cache add-upstream --name ubuntu --url https://archive.ubuntu.com/ubuntu/ \
  --layout classic --path-prefix /ubuntu --suites jammy,noble,noble-updates,noble-security \
  --components main,universe --archs amd64
repo-man cache add-upstream --name debian --url https://deb.debian.org/debian/ \
  --layout classic --path-prefix /debian --suites bookworm,bookworm-updates \
  --components main,contrib --archs amd64

# Publish internal packages
repo-man publish add --path-prefix /local/ /path/to/your-1.0.deb

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

## 4. Kubernetes integration test (kind)

**Goal:** Run repo-man in a local Kubernetes cluster (e.g. [kind](https://kind.sigs.k8s.io/)) and verify that a client pod can install packages via the mirror. Useful for CI or local validation that the same image and config work in K8s.

### Flow

1. **Create cluster:** `kind create cluster` (or use k3d).
2. **Build and load image:** Build the repo-man image, then `kind load docker-image repo-man:test`.
3. **Deploy:** Apply a **Deployment** (repo-man with seed-upstream-then-serve) and a **Service** (ClusterIP on port 8080).
4. **Run client Job:** A **Job** runs an Ubuntu (or other) container that points APT at `http://repo-man:8080/ubuntu`, runs `apt-get update && apt-get install -y <pkg>`, and exits 0 on success.
5. **Tear down:** `kind delete cluster` (or leave the cluster for inspection).

### Manifests and script

Under `tests/k8s/`:

- **manifests/deployment.yaml** — repo-man Deployment; entrypoint seeds Ubuntu upstream if config is missing, then runs `repo-man serve`.
- **manifests/service.yaml** — Service so pods can reach repo-man at `http://repo-man:8080`.
- **manifests/job-apt-client.yaml** — Job that runs Ubuntu, configures APT to use repo-man, and installs a package (e.g. vim).
- **run.sh** — Script that builds the image, creates the kind cluster (if needed), loads the image, applies manifests, and waits for the Job to complete.

Run from project root:

```bash
./tests/k8s/run.sh
```

The same image and config support APT, RPM, and Alpine; the example Job tests APT. You can add RPM or Alpine upstreams to the deployment and add corresponding client Jobs (e.g. Rocky or Alpine image with dnf/apk pointing at repo-man).

### CI

In CI, use a job that has Docker and kind (or k3d) available: create cluster, build and load image, apply manifests, run the client Job, then delete the cluster. Exit non-zero if the Job fails or times out.

---

## See also

- [Operations](operations.md) — config reference, metrics, disk watermark.
- [APT repository types](apt-repo-types.md) — upstream layouts (classic, single-stream) and path prefixes.
- [Architecture](architecture.md) — components and data flow.
