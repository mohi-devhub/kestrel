#!/usr/bin/env bash
# One-command bring-up for the Kestrel data plane:
# kind cluster -> KWOK -> fake GPU nodes -> fake-gpu-operator -> Kueue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="kestrel"

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster '$CLUSTER_NAME' already exists, reusing it."
else
  echo "Creating kind cluster '$CLUSTER_NAME'..."
  kind create cluster --config "${SCRIPT_DIR}/kind/kind-config.yaml"
fi

kubectl config use-context "kind-${CLUSTER_NAME}"

bash "${SCRIPT_DIR}/kwok/install.sh"

echo "Creating 4 fake GPU nodes..."
kubectl apply -f "${SCRIPT_DIR}/kwok/nodes.yaml"

bash "${SCRIPT_DIR}/fake-gpu-operator/install.sh"

echo "Waiting for nvidia.com/gpu capacity to appear on fake nodes..."
for i in $(seq 1 30); do
  GPU_NODES=$(kubectl get nodes -l run.ai/simulated-gpu-node-pool=default -o jsonpath='{range .items[*]}{.status.capacity.nvidia\.com/gpu}{"\n"}{end}' 2>/dev/null | grep -c '[0-9]' || true)
  if [[ "$GPU_NODES" -ge 4 ]]; then
    echo "All 4 fake nodes report GPU capacity."
    break
  fi
  sleep 3
done

bash "${SCRIPT_DIR}/kueue/install.sh"

echo ""
echo "=== Bring-up complete ==="
kubectl get nodes -L run.ai/simulated-gpu-node-pool -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,GPUs:.status.capacity.nvidia\\.com/gpu
