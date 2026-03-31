# APT repository types

Repo-man is format-extensible; APT is the first included format. This page describes the APT upstream and layout types supported on a single service.

## Classic Ubuntu / Debian / GitLab

- **Layout**: Standard `dists/SUITE/COMPONENT/binary-ARCH/` (or `main/amd64/`) and `pool/`. Multiple suites, components, and architectures under one base URL.
- **Example base URLs**: `http://archive.ubuntu.com/ubuntu`, `https://packages.gitlab.com/...`
- **Config**: Add upstream with `--layout classic`, `--path-prefix /ubuntu/`, and optionally `--suites`, `--components`, `--archs` to filter. Suites/components/archs can be discovered from upstream `Release` or restricted in config.

## Kubernetes (pkgs.k8s.io)

- **Layout**: One repo per minor version; standard APT metadata under that path.
- **Example**: `https://pkgs.k8s.io/core:/stable:/v1.34/deb/`
- **Config**: Add one upstream per version with `--layout single-stream`, `--path-prefix /k8s/v1.34/`, `--name k8s-v1.34`.

## CRI-O (OpenBuildService)

- **Layout**: One repo per version; standard APT under `deb/`.
- **Example**: `https://download.opensuse.org/repositories/isv:/cri-o:/stable:/v1.32/deb/`
- **Config**: Same as K8s: `--layout single-stream`, path prefix and name per version.

## Ubuntu ESM Infra

- **Layout**: Classic APT (`dists/<suite>/...` and `pool/...`), usually with suites like `jammy-infra-security` and `jammy-infra-updates`.
- **Example**: `https://esm.ubuntu.com/infra/ubuntu/`
- **Config**: Use `--layout classic` and a dedicated `path_prefix` (e.g. `/ubuntu-esm-infra`), plus upstream auth in config:

```yaml
upstreams:
  - name: ubuntu-esm-infra
    url: https://esm.ubuntu.com/infra/ubuntu/
    layout: classic
    path_prefix: /ubuntu-esm-infra
    suites: [jammy-infra-security, jammy-infra-updates]
    components: [main]
    archs: [amd64]
    auth:
      type: bearer
      token_env: REPO_MIRROR_ESM_TOKEN
```

Set `REPO_MIRROR_ESM_TOKEN` in the runtime environment.
Alternatively, you can set `auth.token` directly in config when needed.

## Local / published

- **Layout**: Same as classic; we generate `dists/` and `pool/` under a path prefix.
- **Config**: No upstream URL. Use `publish add --path-prefix /local/` to publish .deb files. The serve layer serves this prefix from storage (e.g. `local/dists/...`).

## Unified model

- Each **upstream** has: `base_url`, `layout_type` (`classic` | `single-stream`), `path_prefix` for serving, and optional suite/component/arch for classic.
- **Storage keys**: Cache under `cache/<upstream_name>/...`; local under `<path_prefix_stripped>/...` (e.g. `local/`).
- **Serve**: Request path is matched to a path_prefix; the corresponding storage prefix is used to serve files. Clients use multiple `sources.list` entries with different path prefixes on the same host.
