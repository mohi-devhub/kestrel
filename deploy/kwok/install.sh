#!/usr/bin/env bash
# Installs the KWOK controller + CRDs into whatever cluster the current
# kubectl context points at (expects the `foundry` kind cluster).
set -euo pipefail

KWOK_REPO="kubernetes-sigs/kwok"
KWOK_LATEST_RELEASE="$(curl -sL "https://api.github.com/repos/${KWOK_REPO}/releases/latest" | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')"
echo "Installing KWOK ${KWOK_LATEST_RELEASE}..."

kubectl apply -f "https://github.com/${KWOK_REPO}/releases/download/${KWOK_LATEST_RELEASE}/kwok.yaml"
kubectl apply -f "https://github.com/${KWOK_REPO}/releases/download/${KWOK_LATEST_RELEASE}/stage-fast.yaml"

echo "Waiting for kwok-controller to be ready..."
kubectl wait --for=condition=Available deployment/kwok-controller -n kube-system --timeout=120s

echo "KWOK installed."
