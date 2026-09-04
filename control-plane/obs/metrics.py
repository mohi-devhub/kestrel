"""Prometheus metrics, derived from platform state at scrape time.

The control plane runs as three processes — the API server, the reconciler and the
autoscaler — that share one Postgres but no memory. A counter incremented inside
the reconciler is invisible to the API process serving `/metrics`, so anything
that is *state* is computed here from the database and the cluster at collect
time rather than accumulated in a process. That is the same stance
`MeteringStore.usage_for` already takes toward live cost: derive it from the rows,
never keep a second copy that can drift from them.

The one exception is `kestrel_quota_rejections_total`. A rejection is an event, not
a state, and it happens on the API request path and nowhere else — so a plain
in-process counter is both correct and the only way to observe it at all.

The collector degrades rather than fails: if Postgres is unreachable the database
metrics are simply absent from the scrape, and if the cluster is unreachable the
node metrics are, instead of the whole endpoint returning a 500.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from prometheus_client import REGISTRY, Counter
from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
    Metric,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster.protocol import ClusterPort
from db.models import Tenant, Workload
from economics.runway import risk_tier
from metering import EPOCH, MeteringStore
from quota import QuotaEnforcer
from quota.enforcer import ACTIVE_STATUSES
from scheduler.accounting import used_gpus_by_node

logger = logging.getLogger("kestrel.obs")

# Placement runs on a 2s reconcile tick, so most admitted workloads start within a
# few seconds; the long buckets exist to make a queue backing up actually visible.
SCHEDULING_LATENCY_BUCKETS = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0)
# Jobs on KWOK finish almost instantly; endpoints run until torn down.
WORKLOAD_DURATION_BUCKETS = (1.0, 5.0, 15.0, 30.0, 60.0, 300.0, 900.0, 3600.0)

# Workloads waiting for capacity: submitted, not yet running. "admitted" counts —
# Kueue has cleared it but the placement policy has not found it a node yet.
QUEUED_STATUSES = ACTIVE_STATUSES - {"running"}

# The one true in-process counter: rejections happen on the API request path only.
# prometheus_client appends the _total suffix itself.
quota_rejections = Counter(
    "kestrel_quota_rejections",
    "Submissions rejected by the quota enforcer, by tenant",
    ["tenant"],
)


def _cumulative(
    values: list[float], buckets: tuple[float, ...]
) -> tuple[list[tuple[str, float]], float]:
    """Bucket a set of observations into the cumulative form a histogram expects.

    Recomputing from the rows each scrape is still monotonic — the rows are
    append-only and a finished workload never un-finishes — so this satisfies what
    Prometheus expects of a cumulative histogram without a process having to stay
    alive to hold the counts.
    """
    counted: list[tuple[str, float]] = [
        (str(bound), float(sum(1 for v in values if v <= bound))) for bound in buckets
    ]
    counted.append(("+Inf", float(len(values))))
    return counted, float(sum(values))


class KestrelCollector:
    """Reads the platform's own state once per scrape and yields it as metrics."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        cluster_factory: Callable[[], ClusterPort],
    ) -> None:
        self._session_factory = session_factory
        self._cluster_factory = cluster_factory

    def collect(self) -> Iterator[Metric]:
        now = datetime.now(UTC)
        db: Session | None = None
        workloads: list[Workload] = []
        try:
            db = self._session_factory()
            workloads = list(db.execute(select(Workload)).scalars().all())
            tenants = list(db.execute(select(Tenant)).scalars().all())
            yield from self._workload_metrics(workloads, tenants)
            yield from self._tenant_metrics(db, tenants, now)
        except Exception:
            logger.exception("metrics: database collection failed; omitting those series")
        finally:
            if db is not None:
                db.close()

        try:
            yield from self._node_metrics(workloads)
        except Exception:
            logger.exception("metrics: cluster collection failed; omitting node series")

    def _workload_metrics(
        self, workloads: list[Workload], tenants: list[Tenant]
    ) -> Iterator[Metric]:
        slugs = {t.id: t.slug for t in tenants}

        # Every tenant is reported, including at zero — a queue that drains should
        # show a line falling to zero, not a series vanishing from the graph.
        depth = {t.slug: 0 for t in tenants}
        for w in workloads:
            if w.status in QUEUED_STATUSES:
                slug = slugs.get(w.tenant_id)
                if slug is not None:
                    depth[slug] += 1
        queue_depth = GaugeMetricFamily(
            "kestrel_queue_depth",
            "Workloads submitted but not yet running, by tenant",
            labels=["tenant"],
        )
        for slug, count in sorted(depth.items()):
            queue_depth.add_metric([slug], count)
        yield queue_depth

        replicas = GaugeMetricFamily(
            "kestrel_autoscale_replicas",
            "Current replica count of each running endpoint",
            labels=["endpoint", "tenant"],
        )
        for w in workloads:
            if w.kind == "endpoint" and w.status == "running" and w.replicas is not None:
                replicas.add_metric([w.k8s_name, slugs.get(w.tenant_id, "unknown")], w.replicas)
        yield replicas

        # Queue wait: Kueue admission through to actually landing on a node.
        latencies = [
            (w.started_at - w.admitted_at).total_seconds()
            for w in workloads
            if w.admitted_at is not None and w.started_at is not None
        ]
        counted, total = _cumulative(latencies, SCHEDULING_LATENCY_BUCKETS)
        yield HistogramMetricFamily(
            "kestrel_scheduling_latency_seconds",
            "Seconds between Kueue admission and placement on a node",
            buckets=counted,
            sum_value=total,
        )

        duration = HistogramMetricFamily(
            "kestrel_workload_duration_seconds",
            "Seconds a workload spent running, by kind",
            labels=["kind"],
        )
        for kind in ("job", "endpoint"):
            observations = [
                (w.ended_at - w.started_at).total_seconds()
                for w in workloads
                if w.kind == kind and w.started_at is not None and w.ended_at is not None
            ]
            counted, total = _cumulative(observations, WORKLOAD_DURATION_BUCKETS)
            duration.add_metric([kind], counted, sum_value=total)
        yield duration

    def _tenant_metrics(
        self, db: Session, tenants: list[Tenant], now: datetime
    ) -> Iterator[Metric]:
        metering = MeteringStore(db)
        held = QuotaEnforcer(db).running_gpus_by_tenant()

        gpu_seconds = CounterMetricFamily(
            "kestrel_tenant_gpu_seconds",
            "Lifetime GPU-seconds metered to each tenant, open intervals priced to now",
            labels=["tenant"],
        )
        runway = GaugeMetricFamily(
            "kestrel_tenant_runway_seconds",
            "Seconds until a tenant exhausts its GPU-second budget at the current burn rate",
            labels=["tenant"],
        )
        tier = GaugeMetricFamily(
            "kestrel_tenant_risk_tier",
            "Runway risk tier: 0 safe, 3 nearly exhausted",
            labels=["tenant"],
        )
        for t in sorted(tenants, key=lambda t: t.slug):
            usage = metering.usage_for(t.id, EPOCH, now, now)
            gpu_seconds.add_metric([t.slug], float(usage.total_gpu_seconds))

            status = metering.runway_for(t, held.get(t.id, 0), now)
            tier.add_metric([t.slug], risk_tier(status.runway_seconds))
            if status.runway_seconds is not None:
                # An unbudgeted or idle tenant has infinite runway; emit no sample at
                # all rather than a sentinel number a chart would try to plot.
                runway.add_metric([t.slug], float(status.runway_seconds))
        yield gpu_seconds
        yield runway
        yield tier

    def _node_metrics(self, workloads: list[Workload]) -> Iterator[Metric]:
        used = used_gpus_by_node([w for w in workloads if w.status == "running"])
        total = GaugeMetricFamily(
            "kestrel_node_gpu_total", "GPUs a node advertises", labels=["node"]
        )
        in_use = GaugeMetricFamily(
            "kestrel_node_gpu_used",
            "GPUs held by running workloads, from the control plane's own accounting",
            labels=["node"],
        )
        for node in self._cluster_factory().list_nodes():
            # Same view of "the cluster" the scheduler takes in `_build_cluster_state`:
            # a ready node with GPU capacity. The kind control-plane node has none and
            # would only be noise on a GPU map.
            if not node.ready or node.gpu_capacity <= 0:
                continue
            total.add_metric([node.name], node.gpu_capacity)
            in_use.add_metric([node.name], used.get(node.name, 0))
        yield total
        yield in_use


_registered: KestrelCollector | None = None


def register_collector(
    session_factory: Callable[[], Session], cluster_factory: Callable[[], ClusterPort]
) -> KestrelCollector:
    """Register the collector once per process.

    Idempotent: a second call replaces the first rather than double-reporting every
    series, which matters for tests and for any reload that re-imports the app.
    """
    global _registered
    if _registered is not None:
        REGISTRY.unregister(_registered)
    _registered = KestrelCollector(session_factory, cluster_factory)
    REGISTRY.register(_registered)
    return _registered
