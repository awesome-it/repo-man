#!/usr/bin/env bash
# Kubernetes integration test: create kind cluster, deploy repo-man, run apt-client Job.
# Requires: Docker or Podman, kind, kubectl.
# Usage: from project root, ./tests/k8s/run.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANIFESTS="$SCRIPT_DIR/manifests"

# Prefer Podman when available, but allow override via CONTAINER_CLI.
CONTAINER_CLI="${CONTAINER_CLI:-}"
if [ -z "$CONTAINER_CLI" ]; then
  if command -v podman >/dev/null 2>&1; then
    CONTAINER_CLI="podman"
  elif command -v docker >/dev/null 2>&1; then
    CONTAINER_CLI="docker"
  else
    echo "Error: neither podman nor docker found in PATH." >&2
    exit 1
  fi
fi

echo "Using container CLI: $CONTAINER_CLI"

cd "$REPO_ROOT"

echo "Building repo-man image..."
"$CONTAINER_CLI" build -t repo-man:test .

echo "Creating kind cluster (if not present)..."
KIND_CONTEXT="kind-kind"
cluster_ok=
if kubectl get nodes --context "$KIND_CONTEXT" 2>/dev/null | grep -q Ready; then
  cluster_ok=1
  echo "Cluster 'kind' already exists and is reachable."
fi
if [ -z "$cluster_ok" ]; then
  echo "Cluster missing or not reachable; creating..."
  if [ "$CONTAINER_CLI" = "podman" ]; then
    echo "Creating kind cluster with Podman provider (delete + create in same scope)..."
    KIND_EXPERIMENTAL_PROVIDER=podman systemd-run --scope --user -p "Delegate=yes" bash -c 'kind delete cluster --name kind 2>/dev/null; kind create cluster --name kind'
  else
    kind delete cluster --name kind 2>/dev/null || true
    kind create cluster --name kind
  fi
fi

echo "Using kubectl context: $KIND_CONTEXT"
kubectl config use-context "$KIND_CONTEXT"

echo "Loading image into kind..."
if [ "$CONTAINER_CLI" = "podman" ]; then
  KIND_EXPERIMENTAL_PROVIDER=podman systemd-run --scope --user -p "Delegate=yes" kind load docker-image repo-man:test --name kind
else
  kind load docker-image repo-man:test --name kind
fi

echo "Applying manifests..."
kubectl apply -f "$MANIFESTS/deployment.yaml"
kubectl apply -f "$MANIFESTS/service.yaml"

echo "Waiting for repo-man Deployment to be ready..."
kubectl wait --for=condition=available deployment/repo-man --timeout=120s

echo "Running apt-client Job..."
kubectl apply -f "$MANIFESTS/job-apt-client.yaml"
kubectl wait --for=condition=complete job/apt-client --timeout=300s

echo "K8s integration test passed."
echo "To tear down: kind delete cluster --name kind"
