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
- [x] Reconcile loop (admitted → placed → running → closed, multi-GPU all-or-nothing)
- [x] `POST /admin/policy` to switch active policy
- [x] Utilization/wait metrics recorded (`GET /cluster/nodes|workloads`, `placement_policy` column, admission/start timestamps)
- [x] CHECKPOINT shown to user

## Phase 3 — Metering, quota, billing
- [x] `MeteringStore`: open/close interval, partials, `usage_for`
- [x] `QuotaEnforcer`: admission, placement, budget checks
- [x] `Billing`: report generation
- [x] Unit tests: metering math
- [x] Unit tests: billing math
- [x] Unit tests: quota math
- [x] Wire quota into admission + placement
- [x] `GET /tenants/{id}/usage`
- [x] `GET /tenants/{id}/billing-report`
- [x] CHECKPOINT shown to user

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

### Phase 2 (2026-08-31)
Shipped: manual Kueue integration (control plane creates `Workload` CRs itself; the real K8s Job is created only after Kueue admits AND the active policy picks a node — Kueue's automatic Job integration is retired since it hands node choice to the default scheduler); `scheduler/` with a pure `PlacementPolicy` interface + `first_fit`, `bin_packing`, `priority` (priority = ordering pass; node selection reuses first-fit); reconcile loop as a standalone compose service (`python -m scheduler.reconcile`, single writer of workload status — API routes now read Postgres only); `POST/GET /admin/policy` (Redis-backed, live-swappable); `GET /cluster/nodes` + `/cluster/workloads` (control-plane GPU accounting, since KWOK bypass means K8s allocatable can't be trusted); `placement_policy` column + status index migration; state-conditional idempotent cancel/teardown.

Verified: 28/28 tests (10 pure policy, 8 reconcile-vs-FakeCluster, integration incl. oversubscription drain, live policy swap changing node choice, multi-GPU all-or-nothing under fragmentation); live checkpoint demo through the containerized stack.

Lessons/deviations: (1) Kueue refuses to admit a Workload requesting any resource the ClusterQueue doesn't cover — the podSet must request GPU only (a nominal `cpu` request wedged everything at `QuotaReserved=False`). (2) `SessionLocal(autoflush=False)` hid same-tick admissions from the placement step's SELECT — explicit `db.flush()` between reconcile steps. (3) Endpoint replicas all pin to one node via the shared pod template, so accounting budgets `gpus × min_replicas`. (4) Per-workload `priority` is deliberately NOT fed into Kueue's own admission ordering (would need WorkloadPriorityClass bootstrap); it drives our placement ordering only.

### Phase 3 (2026-09-02)
Shipped: `metering/` (`MeteringStore` — append-only usage intervals opened at placement and closed at completion/cancel, `record_partial` rotation for Phase 4's replica changes, `usage_for` clipping intervals to a period and pricing open ones to `now`); `quota/` (`QuotaEnforcer` — in-flight workload cap + impossible-ask rejection + lifetime budget at admission, per-tenant concurrent-GPU gate at placement); `billing/` (`Billing.report` — per-workload cost table persisted as append-only `billing_snapshots`); `GET /tenants/{id}/usage` and `GET /tenants/{id}/billing-report` (tenant-scoped, 404 cross-tenant); `usage_events` + `billing_snapshots` tables and indexes.

Verified: 59/59 tests (27 new Phase 3 unit/flow + 4 new live integration + existing suite), ruff/mypy clean, migration up/down round-tripped on live Postgres. Live checkpoint through the containerized stack: a 2-GPU endpoint accruing 8.08 → 24.11 → 40.15 GPU-seconds across 8s reads (exactly 2 GPUs × elapsed), billing report totalling 40.19 GPU-seconds = $0.14 at $12.50/GPU-hour, a 5-GPU ask on a 4-GPU quota rejected 429, teardown freezing accrual, and a 10 GPU-second budget blocking the next submission once crossed.

Lessons/deviations: (1) **Admission deliberately does NOT count queued/admitted GPUs against `max_gpus`** — waiting in line beyond current capacity is exactly Kueue's queueing model, so admission only rejects an ask larger than the tenant's entire quota (it could never run and would wedge the queue forever); concurrency is enforced at *placement*, which is also the only gate endpoints get since they skip Kueue. (2) The autoflush lesson from Phase 2 recurred twice: the placement loop keeps an in-memory per-tenant GPU tally (a re-query would miss same-tick placements, mirroring `ClusterState.reserve`), and `MeteringStore` checks instance state before closing an interval (a row closed earlier in the same transaction still matches the "open" SQL filter). (3) No timer-driven partial records — live cost is derived by pricing open intervals to `now` at read time, which is exact, append-only, and writes nothing. (4) KWOK auto-completes fake Job pods almost instantly, so demonstrating live accrual needs an endpoint (Deployment), not a job.
