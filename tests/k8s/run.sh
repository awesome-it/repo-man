#!/usr/bin/env bash
# Kubernetes integration test: create kind cluster, deploy repo-man, run apt-client Job.
# Requires: Docker, kind, kubectl.
# Usage: from project root, ./tests/k8s/run.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANIFESTS="$SCRIPT_DIR/manifests"

cd "$REPO_ROOT"

echo "Building repo-man image..."
docker build -t repo-man:test .

echo "Creating kind cluster (if not present)..."
if ! kind get clusters 2>/dev/null | grep -q kind; then
  kind create cluster --name kind
else
  echo "Cluster 'kind' already exists."
fi

echo "Loading image into kind..."
kind load docker-image repo-man:test --name kind

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
