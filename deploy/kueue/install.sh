#!/usr/bin/env bash
# Installs Kueue (Kubernetes-native job queueing/admission) at its latest release.
set -euo pipefail

KUEUE_REPO="kubernetes-sigs/kueue"
KUEUE_LATEST_RELEASE="$(curl -sL "https://api.github.com/repos/${KUEUE_REPO}/releases/latest" | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')"
echo "Installing Kueue ${KUEUE_LATEST_RELEASE}..."

kubectl apply --server-side -f "https://github.com/${KUEUE_REPO}/releases/download/${KUEUE_LATEST_RELEASE}/manifests.yaml"

echo "Waiting for kueue-controller-manager to be ready..."
kubectl wait --for=condition=Available deployment/kueue-controller-manager -n kueue-system --timeout=180s

echo "Kueue installed."
