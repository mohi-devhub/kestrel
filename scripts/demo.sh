#!/usr/bin/env bash
# End-to-end tour of Kestrel against the live stack.
#
# Shows the two things that are genuinely hard to fake: a real model serving
# real inference on the one node that can execute containers, and the control
# plane's own accounting of a fleet that is mostly simulated. Read the KUBELET
# column in the fleet table — nodes reporting a version are real, the ones
# reporting nothing are KWOK.
#
# Prerequisites: deploy/bootstrap.sh has run, `cd deploy && docker compose up -d`
# is healthy, and the demo image is built and side-loaded (this script does that
# for you if it is missing).
set -euo pipefail

API="${KESTREL_API:-http://127.0.0.1:8000}"
ADMIN_TOKEN="${KESTREL_ADMIN_TOKEN:-dev-admin-token}"
IMAGE="kestrel/embed-service:v1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$REPO_ROOT/deploy/kubeconfig/host.yaml}"

PF_PID=""
ENDPOINT_ID=""
KEY=""

cleanup() {
  [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null || true
  if [ -n "$ENDPOINT_ID" ] && [ -n "$KEY" ]; then
    curl -s -X DELETE "$API/endpoints/$ENDPOINT_ID" -H "x-kestrel-key: $KEY" >/dev/null || true
  fi
}
trap cleanup EXIT

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
json() { python3 -c "import sys,json; d=json.load(sys.stdin); $1"; }

# --- preflight ----------------------------------------------------------------
curl -sf "$API/healthz" >/dev/null || { echo "control plane is not up at $API"; exit 1; }

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  say "Building the demo model image (first run only)"
  docker build -t "$IMAGE" "$REPO_ROOT/demo/embed-service"
fi
if ! docker exec kestrel-worker crictl images 2>/dev/null | grep -q embed-service; then
  say "Side-loading the model image onto the real worker"
  kind load docker-image "$IMAGE" --name kestrel --nodes kestrel-worker
fi

# --- 1. the fleet -------------------------------------------------------------
say "1. The fleet: one real worker, four simulated GPU nodes"
echo "   KUBELET is the tell — a real node reports a version, KWOK reports nothing."
kubectl get nodes -o 'custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,KUBELET:.status.nodeInfo.kubeletVersion,GPUS:.status.capacity.nvidia\.com/gpu'

# --- 2. tenants ---------------------------------------------------------------
say "2. Tenants"
KESTREL_API="$API" KESTREL_ADMIN_TOKEN="$ADMIN_TOKEN" python3 "$REPO_ROOT/scripts/seed.py" > /tmp/kestrel-seed.$$ 
sed -n '1,4p' /tmp/kestrel-seed.$$
KEY=$(grep KESTREL_KEY_RESEARCH /tmp/kestrel-seed.$$ | cut -d= -f2)
rm -f /tmp/kestrel-seed.$$

# --- 3. schedule a real model onto the CPU pool -------------------------------
say "3. Scheduling a real model (no GPUs) — it must land on the real worker"
ENDPOINT_ID=$(curl -s -X POST "$API/endpoints" -H "x-kestrel-key: $KEY" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"demo-embeddings\",\"image\":\"$IMAGE\",\"port\":8080,\"gpus\":0,\"min_replicas\":1}" \
  | json "print(d['id'])")

for _ in $(seq 1 60); do
  read -r STATUS NODE <<<"$(curl -s "$API/endpoints/$ENDPOINT_ID" -H "x-kestrel-key: $KEY" \
    | json "print(d['status'], d['node_name'])")"
  [ "$STATUS" = "running" ] && break
  sleep 1
done
echo "   placed: status=$STATUS node=$NODE"
[ "$NODE" = "kestrel-worker" ] || { echo "   FAIL: expected the CPU pool"; exit 1; }

K8S_NAME=$(curl -s "$API/endpoints/$ENDPOINT_ID" -H "x-kestrel-key: $KEY" | json "print(d['k8s_name'])")
kubectl wait --for=condition=ready pod -l "app=$K8S_NAME" -n tenant-research --timeout=180s >/dev/null
kubectl get pods -n tenant-research -l "app=$K8S_NAME" \
  -o 'custom-columns=POD:.metadata.name,NODE:.spec.nodeName,READY:.status.containerStatuses[0].ready,CONTAINER:.status.containerStatuses[0].containerID'

# --- 4. real inference --------------------------------------------------------
say "4. Real inference through the scheduled endpoint"
kubectl port-forward -n tenant-research "svc/$K8S_NAME" 8081:8080 >/dev/null 2>&1 &
PF_PID=$!
# Detach it from job control, so killing it in the trap does not make bash
# print a 'Terminated' notice over the demo's last line of output.
disown "$PF_PID" 2>/dev/null || true
for _ in $(seq 1 30); do curl -sf http://127.0.0.1:8081/healthz >/dev/null 2>&1 && break; sleep 1; done
curl -s http://127.0.0.1:8081/healthz | json "print('  ', d['model'], '/', d['dimensions'], 'dimensions')"
python3 - <<'PY'
import json, urllib.request
PAIRS = [
    ("a GPU scheduler places jobs on nodes", "a cluster orchestrator assigns work to machines"),
    ("the model is training on eight GPUs", "the run is using eight accelerators"),
    ("a GPU scheduler places jobs on nodes", "I baked banana bread this morning"),
]
for a, b in PAIRS:
    req = urllib.request.Request("http://127.0.0.1:8081/similarity",
        data=json.dumps({"a": a, "b": b}).encode(),
        headers={"content-type": "application/json"})
    d = json.load(urllib.request.urlopen(req))
    print(f"   cos={d['cosine_similarity']:+.4f}  {d['inference_ms']:5.1f}ms   {a[:34]!r} / {b[:34]!r}")
PY

# --- 5. GPU work goes to the other pool ---------------------------------------
say "5. GPU work goes to the simulated pool instead"
JOB_ID=$(curl -s -X POST "$API/jobs" -H "x-kestrel-key: $KEY" -H 'content-type: application/json' \
  -d '{"name":"demo-train","image":"busybox:1.36","command":["sh","-c","sleep 30"],"gpus":2}' \
  | json "print(d['id'])")
for _ in $(seq 1 30); do
  read -r JSTATUS JNODE <<<"$(curl -s "$API/jobs/$JOB_ID" -H "x-kestrel-key: $KEY" \
    | json "print(d['status'], d['node_name'])")"
  case "$JSTATUS" in running|succeeded) break;; esac
  sleep 1
done
echo "   2-GPU job: status=$JSTATUS node=$JNODE"

# --- 6. why did it decide that? ----------------------------------------------
say "6. Decision explainability"
curl -s "$API/workloads/$JOB_ID/explain" -H "x-kestrel-key: $KEY" | json "
print('   quota passes    ', d['quota']['passes'], d['quota']['reason'] or '')
print('   kueue admitted  ', d['kueue_admitted'])
r = d['runway']
print('   burn rate       ', r['burn_rate_gpus'], 'GPUs')
print('   runway seconds  ', r['runway_seconds'])
print('   risk tier       ', r['risk_tier'], '(0 healthy .. 3 exhausted)')
o = d.get('ordering')
print('   ordering        ', 'n/a (already placed)' if o is None else o)"

# --- 7. metering --------------------------------------------------------------
say "7. Metered usage and derived cost"
TENANT_ID=$(curl -s "$API/admin/tenants" -H "x-kestrel-admin-token: $ADMIN_TOKEN" \
  | json "print(next(t['id'] for t in d if t['slug']=='research'))")
curl -s "$API/tenants/$TENANT_ID/usage" -H "x-kestrel-key: $KEY" | json "
print('   period      ', d['period_start'][:10], '->', d['period_end'][:10])
print('   gpu-seconds ', d['total_gpu_seconds'])
print('   cost        ', '\$' + d['estimated_cost'])
print('   workloads   ', len(d['workloads']))"

say "Done — tearing down the demo endpoint"
