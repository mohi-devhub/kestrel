#!/usr/bin/env bash
# Installs run-ai/fake-gpu-operator (classic device-plugin mode, KWOK-aware
# by default) so the 4 fake KWOK nodes advertise nvidia.com/gpu capacity.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${FAKE_GPU_OPERATOR_VERSION:-}"

if [[ -z "$VERSION" ]]; then
  VERSION="$(helm show chart oci://ghcr.io/run-ai/fake-gpu-operator/fake-gpu-operator 2>/dev/null | grep '^version:' | awk '{print $2}')"
fi
echo "Installing fake-gpu-operator ${VERSION}..."

helm upgrade -i gpu-operator oci://ghcr.io/run-ai/fake-gpu-operator/fake-gpu-operator \
  --namespace gpu-operator --create-namespace \
  --version "$VERSION" \
  -f "${SCRIPT_DIR}/values.yaml" \
  --wait --timeout 180s

echo "fake-gpu-operator installed."
