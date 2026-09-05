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

# Kubeconfigs, regenerated every run: recreating the cluster changes the API
# server's address and certificate, so a stale pair silently breaks every
# service. `--internal` addresses the API server by its Docker-network hostname,
# which is how the containerized control plane reaches it; the plain one uses
# 127.0.0.1 for local dev and tests.
echo "Writing kubeconfigs to ${SCRIPT_DIR}/kubeconfig/ ..."
mkdir -p "${SCRIPT_DIR}/kubeconfig"
kind get kubeconfig --name "$CLUSTER_NAME" > "${SCRIPT_DIR}/kubeconfig/host.yaml"
kind get kubeconfig --name "$CLUSTER_NAME" --internal > "${SCRIPT_DIR}/kubeconfig/internal.yaml"

echo ""
echo "=== Bring-up complete ==="
# KUBELET distinguishes the two pools at a glance: real nodes report a version,
# KWOK's simulated ones report nothing because no kubelet exists to report it.
# READY selects the Ready condition by name rather than taking the last one in
# the list, which on a KWOK node is NetworkUnavailable and reads like a failure.
kubectl get nodes -o 'custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,KUBELET:.status.nodeInfo.kubeletVersion,GPUS:.status.capacity.nvidia\.com/gpu'
