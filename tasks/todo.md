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
- [x] `autoscale_events` table + `workloads.replicas` column (migration)
- [x] Replica-aware GPU accounting (`workload_gpus`), wired into node/quota/placement
- [x] `LoadSignal`: reported-load ingest + Redis rolling window
- [x] `AutoscalePolicy`: pure `decide()` + `clamp_to_capacity()`
- [x] `autoscale_once` loop: scale Deployment, rotate usage interval, record events
- [x] Scale-to-zero on idle (min_replicas=0) + wake from zero
- [x] `control_lock` shared by reconciler and autoscaler
- [x] `POST/GET /endpoints/{id}/load`, `GET /endpoints/{id}/autoscale-events`
- [x] `scripts/loadgen.py`
- [x] Unit tests: autoscale decision math
- [x] Integration tests: autoscale loop + load API
- [x] CHECKPOINT shown to user

## Phase 5 — Runway-aware scheduling + decision explainability
Not in the original `docs/PHASES.md` — the differentiator identified after Phase 4: a tenant's runway (budget remaining ÷ burn rate) becomes a first-class scheduling/autoscaling signal, not just a billing number, and every admission/placement decision becomes inspectable.
- [x] `economics/runway.py`: pure `burn_rate` / `runway_seconds` over `usage_for` output
- [x] `PlacementCandidate.tenant_runway_seconds` (computed once per reconcile tick, passed in like `ClusterState`)
- [x] `RunwayFair` placement policy (`order()` by `(-priority, risk_tier, admitted_at)`, no-budget fallback to tier 0, starvation floor promotes long-waiting candidates to tier 0)
- [x] `clamp_to_capacity` budget-headroom clamp: autoscaler won't scale an endpoint past what its remaining runway affords
- [x] `GET /workloads/{id}/explain`: reconstructs quota check, admission status, active policy's ordering, and the runway numbers behind it, from stored state only
- [x] `POST /admin/policy` accepts `runway_fair` (free once registered in `POLICIES`)
- [x] Unit tests: runway math, `RunwayFair` ordering (incl. no-budget fallback, starvation floor), budget-clamped autoscale
- [x] CHECKPOINT shown to user

## Phase 6 — Observability + dashboard

### 6a — Metrics (control plane)
The three control-plane processes (api, reconciler, autoscaler) share one Postgres but no memory, so
in-process counters incremented in the reconciler would be invisible on the API's `/metrics`. State
metrics are therefore *derived at scrape time* from Postgres + the cluster client by a custom
collector — the same derive-on-read stance `usage_for` already takes. Only genuinely API-process
events (quota rejections) use a plain in-process counter.
- [x] `prometheus_client` dependency
- [x] `obs/metrics.py`: custom collector — queue depth, node GPU used/total, tenant GPU-seconds, autoscale replicas, scheduling latency, workload duration (all `docs/PLAN.md` §8)
- [x] Runway gauges (`tenant_runway_seconds`, `tenant_risk_tier`) — beyond §8, surfaces Phase 5 on the dashboard
- [x] `kestrel_quota_rejections_total` counter wired into job/endpoint admission
- [x] `GET /metrics` on the API app, degrading to empty rather than 500 if the DB is down
- [x] Unit tests: collector output against real rows
- [x] Prometheus service + scrape config in docker-compose
- [x] Fix test-tenant leak: 9 suites created tenants and never swept them (454 rows, ~1400 junk series). Session-scoped sweep in `conftest.py`, pattern-matched so hand-made demo tenants survive.

### 6b — Dashboard scaffold
- [x] `GET /admin/tenants` (list) — the dashboard can't enumerate tenants today
- [x] Next.js (App Router, TS) + Tailwind + shadcn/ui
- [x] Server-side client + server actions holding the admin token, minting a real per-tenant key on demand (no tokens in browser, no CORS needed)
- [x] Base layout + tenant/cluster nav, auto-refresh that pauses on a hidden tab
- [x] Dockerfile (standalone output) + compose service, so one-command bring-up still holds

### 6c — Tenant view
- [x] Tenant list + submit forms (job / endpoint)
- [x] Workload table (status, node, policy, replicas)
- [x] Usage + cost panel, quota bars, budget/runway with risk tier
- [x] Explain row expansion on a workload (Phase 5's `/explain`)

### 6d — Cluster view
- [x] Node GPU map (per-node used/free, who holds what)
- [x] Active policy switcher (the demo lever)
- [x] Live autoscaling + queue-depth + GPU-in-use charts from Prometheus range queries

- [ ] CHECKPOINT shown to user

## Phase 7 — Integration demo + polish
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

### Phase 4 (2026-09-02)
Shipped: `autoscale/` (`LoadSignal` — reported requests in a Redis sorted-set sliding window; `policy.py` — pure `decide()` turning observed RPS into a replica target with scale-to-zero, wake-from-zero and a scale-down stabilization window, plus `clamp_to_capacity()` limiting a scale-up to the pinned node's free GPUs and the tenant's quota headroom; `loop.py` — `autoscale_once` patching the Deployment, rotating the usage interval onto the new footprint and appending `autoscale_events`, run as its own compose service); `workloads.replicas` column + `autoscale_events` table; `workload_gpus()` so node accounting, tenant quota and metering all read an endpoint's *live* footprint; `control_lock` (Redis mutex with a Lua compare-and-delete release) shared by the reconciler and the autoscaler; `POST/GET /endpoints/{id}/load` and `GET /endpoints/{id}/autoscale-events`; `scripts/loadgen.py`.

Verified: 100/100 tests (23 pure decision-math + 9 loop-vs-FakeCluster + 7 load-API + 2 new live, plus the existing suite), ruff clean, mypy clean on 47 source files, migration down/up round-tripped on live Postgres. Live checkpoint through the containerized stack: an endpoint provisioned at `min_replicas=0` placed cold (0 replicas, 0 GPU-seconds, $0), woken by reported load and climbing 0→1→2→3 replicas as the window filled, confirmed against the real Deployment (`kubectl` replicas and pod count both 3) and the node's GPU accounting (`gpu_used=3`), stepped back down 3→2→1 with the two scale-downs exactly 30s apart, then asleep at 0 replicas 65s after traffic stopped with all 4 GPUs returned to the node; usage frozen at 261.366746 GPU-seconds across two reads 8s apart, billed $0.91 at $12.50/GPU-hour.

Lessons/deviations: (1) **The repo was not actually mypy-clean under `control-plane/.venv`** — `redis.Redis` is not generic in redis-py 5.2.1 (so the `Redis[str]` annotations added in Phase 3 were errors) and SQLAlchemy's dialect-type constructors are untyped. Earlier "clean" runs must have used an environment that couldn't resolve those packages. Fixed at the source (plain `Redis`, pass the type class instead of instantiating it) rather than with ignores, which would have gone stale the same way. (2) A package `__init__` must not import the module that gets run as `python -m` — re-exporting `autoscale.loop` made runpy execute it twice and warn. (3) The sliding window makes scale-up *gradual* even under perfectly constant traffic, because the observed rate climbs as the window fills; that's the same shape as Knative's stable window and is worth keeping, not smoothing away. (4) Simulating elapsed time by passing an explicit `now` into `autoscale_once` let the live test cover the 60s idle window without sleeping through it — the load signal's timestamps are real, so a future `now` is indistinguishable from having waited. (5) Scale-to-zero *closes* the usage interval rather than reopening one at 0 GPUs, so a sleeping endpoint has no open row at all and cost visibly flatlines. (6) Two loops now write workload rows, so rather than making each independently safe they share one short Redis mutex per tick — Phase 2's single-writer invariant is preserved in effect, and it rules out the two loops double-booking a node's GPUs.

### Phase 5 (2026-09-03)
Shipped: `economics/runway.py` (pure `burn_rate`, `remaining_budget`, `runway_seconds`, `risk_tier`, `budget_headroom_gpus`, all None-is-infinite for unbudgeted/idle tenants); `MeteringStore.runway_for` (the one place a tenant's runway is actually computed from usage history, called identically by the scheduler, the autoscaler, and the explain endpoint — moved the shared `EPOCH` lifetime-window constant from `quota/enforcer.py` into `metering` so all three could import it without a circular dependency); `PlacementCandidate.tenant_runway_seconds` + `PlacementPolicy.order(candidates, now)` (interface gained `now`, mirroring why `autoscale.policy.decide` already takes it, so a policy can reason about wait time without reading the wall clock itself); `RunwayFair` policy (ordering only — node selection stays first-fit — sorting `(-priority, risk_tier, admitted_at)` with a 300s starvation floor that promotes a long-waiting low-runway candidate back to tier 0, so runway can delay a placement but never lock one out indefinitely); `clamp_to_capacity`'s new `budget_headroom_gpus` parameter (default `None` = unconstrained, preserving every existing call site) folded into the existing tightest-of-three-limits clamp, backed by a new `budget_headroom_horizon_seconds` setting; `scheduler/explain.py` + `GET /workloads/{id}/explain` (`api/routers/workloads.py`) — a genuine read-only dry run reusing `ClusterState`/`PlacementCandidate`/the active policy/`QuotaEnforcer.check_placement` to report quota pass/fail, Kueue admission (jobs only), this tick's ordering rank and would-place-on-node-or-why-not, and the full runway picture, all without creating anything.

Verified: once Docker was available, 156/156 tests pass against the real containerized stack (docker-compose Postgres/Redis + the live kind+KWOK+Kueue cluster) — including the 5 tests that need a real cluster (`test_phase0_cluster.py`, `test_phase1_tenants.py`, `test_phase2_placement.py`, `test_phase3_live.py`, `test_phase4_live.py`) that an earlier, Docker-less pass of this phase could only skip; ruff and mypy strict clean on all 52 control-plane source files. Live CHECKPOINT through the real stack: switched the active policy to `runway_fair` via `POST /admin/policy`; a tenant with a 5 GPU-second budget ran a 1-GPU endpoint past exhaustion, and `GET /workloads/{id}/explain` reported `runway_seconds: 0`, `risk_tier: 3`, `is_exhausted: true` and `quota.passes: false` with the exact reason a subsequent real submission was then rejected with (429) — proving explain's prediction and the real admission gate agree. Then the ordering itself: a tenant with 400 GPU-second budget (already burning 1 GPU, runway ~372s, risk_tier 2) submitted a job *first*; an unbudgeted tenant (infinite runway, risk_tier 0) submitted a job *second* — under `runway_fair`, `explain` showed the healthy tenant's later job at rank 0 and the low-runway tenant's earlier job at rank 1, the exact FIFO-defying flip the policy is for. All demo workloads/tenants cancelled afterward.

Lessons/deviations: (1) Runway computation ended up needing DB access (usage history), so it couldn't live in the pure `economics.runway` module alongside the math it's built from — it's a `MeteringStore` method instead, keeping `economics/runway.py`'s "no DB" promise intact while still giving the scheduler, autoscaler and explain endpoint one shared implementation. (2) `_place_admitted`'s existing apply-loop logic was left untouched (only the candidate-building step gained `now`/runway) rather than refactored into a shared decide/apply split with `explain.py`, since that refactor couldn't be verified against live Postgres in this environment and the existing loop already has real test coverage riding on its current shape — `scheduler/explain.py` therefore duplicates the small ordering-simulation loop rather than sharing it byte-for-byte; worth collapsing once the live suite can confirm a refactor is safe. (3) `RunwayFair` only reorders placement among *admitted* candidates — Kueue admission and `QuotaEnforcer`'s hard budget block happen earlier and are unaffected, which is deliberate: runway is a tie-breaker among already-admitted work, not a new gate.
