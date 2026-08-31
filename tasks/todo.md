# Kestrel — todo

Full spec: `docs/PLAN.md`. Checkpoints per `docs/PHASES.md`. Check items off as completed; don't batch.

## Phase 0 — Cluster + control-plane skeleton
- [x] kind cluster config
- [x] KWOK installed
- [x] `run-ai/fake-gpu-operator` installed, fake GPU nodes visible (`kubectl get nodes` shows `nvidia.com/gpu`) — 4 nodes x 4 GPUs
- [x] Kueue installed, healthy
- [x] docker-compose: control-plane + Postgres + Redis
- [x] FastAPI skeleton + config + `.env.example`
- [x] `ClusterClient` wrapping K8s Python client (list nodes/capacity)
- [x] `ClusterClient` create + delete a trivial Job
- [x] CHECKPOINT shown to user

## Phase 1 — Tenants, API keys, multi-tenancy
- [x] Tenant CRUD (Postgres model + API)
- [x] API-key auth middleware
- [x] Namespace + ResourceQuota + Kueue LocalQueue bootstrap on tenant creation
- [x] `POST /jobs` (naive placement)
- [x] `POST /endpoints` (naive placement)
- [x] Verify tenant isolation (2-3 tenants, cross-tenant access blocked)
- [x] CHECKPOINT shown to user

## Phase 2 — Placement policies on Kueue
- [x] Kueue ClusterQueue + ResourceFlavor for fake GPUs (shipped in Phase 1's tenant bootstrap)
- [x] `PlacementPolicy` interface
- [x] `FirstFit` policy
- [x] `BinPacking` policy
- [x] `Priority` policy
- [ ] Reconcile loop (admitted → placed → running → closed, multi-GPU all-or-nothing) — built, pending verification against Postgres/Redis + kind
- [ ] `POST /admin/policy` to switch active policy — built, pending live verification
- [ ] Utilization/wait metrics recorded (`GET /cluster/nodes|workloads`, `placement_policy` column) — built, pending live verification
- [ ] CHECKPOINT shown to user

## Phase 3 — Metering, quota, billing
- [ ] `MeteringStore`: open/close interval, partials, `usage_for`
- [ ] `QuotaEnforcer`: admission, placement, budget checks
- [ ] `Billing`: report generation
- [ ] Unit tests: metering math
- [ ] Unit tests: billing math
- [ ] Unit tests: quota math
- [ ] Wire quota into admission + placement
- [ ] `GET /tenants/{id}/usage`
- [ ] `GET /tenants/{id}/billing-report`
- [ ] CHECKPOINT shown to user

## Phase 4 — Autoscaling
- [ ] Custom autoscaler loop (queue-depth/load → replicas)
- [ ] Scale-to-zero on idle
- [ ] `scripts/loadgen.py`
- [ ] `autoscale_events` recorded
- [ ] CHECKPOINT shown to user

## Phase 5 — Observability + dashboard
- [ ] Prometheus metrics wired (full list in `docs/PLAN.md` §8)
- [ ] Next.js app scaffold + shadcn/ui
- [ ] Tenant view (submit, running workloads, usage/cost, quota bars)
- [ ] Cluster view (GPU map, autoscaling live)
- [ ] CHECKPOINT shown to user

## Phase 6 — Integration demo + polish
- [ ] Small real CPU model chosen + verified runnable
- [ ] Model served as demo endpoint (model-agnostic interface)
- [ ] `scripts/seed.py`
- [ ] `scripts/demo.sh`
- [ ] `README.md`
- [ ] Full end-to-end demo run
- [ ] CHECKPOINT shown to user

## Optional epilogue
- [ ] Real rented GPU node (Vast.ai/RunPod spot) serving a real request — decide after Phase 6

## Review
(fill in after each phase: what shipped, what changed from plan, lessons)

### Phase 0 (2026-08-16)
Shipped: `deploy/bootstrap.sh` brings up kind + KWOK + fake-gpu-operator (4 nodes x 4 sim GPUs) + Kueue in one command; `control-plane/` FastAPI skeleton with `/healthz` (live DB/Redis/K8s checks, no hardcoded values) and `ClusterClient` (list_nodes, create_job, delete_job, get_job_status); `deploy/docker-compose.yml` runs control-plane + Postgres + Redis, with the control-plane container joined to the `kind` docker network so it reaches the cluster's real API server. Verified: a pod requesting `nvidia.com/gpu: 1` schedules onto a fake node via the normal kube-scheduler; `tests/test_phase0_cluster.py` passes against the live cluster; ruff/mypy clean.

Deviations from `docs/PLAN.md`: none architecturally. One detail the plan didn't spell out — the control-plane container needs `kind get kubeconfig --internal` (not the default host kubeconfig) to reach the API server by Docker-network hostname instead of `127.0.0.1`. Two kubeconfigs are now generated into `deploy/kubeconfig/` (gitignored): `host.yaml` for local dev/tests, `internal.yaml` for the containerized control plane.
