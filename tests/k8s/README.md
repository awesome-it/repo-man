# Kubernetes integration test

Runs repo-man in a local Kubernetes cluster (kind) and verifies that an APT client Job can install packages via the mirror.

## Prerequisites

- Docker
- [kind](https://kind.sigs.k8s.io/) (Kubernetes in Docker)
- kubectl

## Run

From the project root:

```bash
./tests/k8s/run.sh
```

The script will:

1. Build the repo-man Docker image
2. Create a kind cluster (if one does not exist)
3. Load the image into the cluster
4. Apply Deployment and Service for repo-man (seeds Ubuntu upstream, then serves)
5. Run a Job that uses repo-man as APT source and installs `vim`
6. Exit 0 if the Job completes successfully

## Tear down

```bash
kind delete cluster --name kind
```

## Manifests

- `manifests/deployment.yaml` — repo-man Deployment (single replica, emptyDir for cache)
- `manifests/service.yaml` — ClusterIP Service so pods can reach repo-man at `http://repo-man:8080`
- `manifests/job-apt-client.yaml` — Job running Ubuntu with APT pointed at repo-man

The same image and config pattern support APT, RPM, and Alpine; the Job here tests APT only. You can add RPM or Alpine upstreams to the deployment entrypoint and corresponding client Jobs if desired.
