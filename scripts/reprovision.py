"""Rebuild the Kubernetes objects backing existing tenants.

The cluster is disposable — it's kind plus KWOK, and recreating it is a normal
operation — but the database is not: `usage_events` is an append-only ledger of
real accrued usage. Deleting the cluster destroys every tenant namespace,
ResourceQuota and Kueue queue while leaving the tenant rows that reference them,
so the two halves fall out of sync and submissions fail against a namespace that
no longer exists.

Purging and re-seeding the tenants would resolve that by throwing away the
ledger, which is the wrong half to sacrifice. Provisioning is written as
`ensure_*`, so re-running it against a fresh cluster is safe and converges: this
replays it for every tenant already in the database.

Run it from the repo root, after `deploy/bootstrap.sh` has written a fresh
kubeconfig. The path must be absolute — the client resolves it itself:

    KUBECONFIG_PATH=$PWD/deploy/kubeconfig/host.yaml \
        PYTHONPATH=control-plane control-plane/.venv/bin/python \
        scripts/reprovision.py
"""

from __future__ import annotations

import sys

from cluster import ClusterClient
from cluster.naming import tenant_cluster_queue, tenant_local_queue, tenant_namespace
from config import settings
from db import SessionLocal
from db.models import Tenant
from sqlalchemy import select


def main() -> int:
    cluster = ClusterClient(kubeconfig_path=settings.kubeconfig_path)
    db = SessionLocal()
    try:
        tenants = list(db.execute(select(Tenant).order_by(Tenant.slug)).scalars())
        if not tenants:
            print("no tenants to reprovision")
            return 0

        # Cluster-scoped and shared across tenants, so it is ensured once rather
        # than redundantly per tenant.
        cluster.ensure_resource_flavor()

        for t in tenants:
            namespace = tenant_namespace(t.slug)
            cluster.ensure_namespace(namespace)
            cluster.ensure_resource_quota(namespace, t.max_gpus, t.max_workloads)
            cluster.ensure_cluster_queue(tenant_cluster_queue(t.slug), t.max_gpus)
            cluster.ensure_local_queue(
                namespace, tenant_local_queue(t.slug), tenant_cluster_queue(t.slug)
            )
            print(f"reprovisioned {t.slug} -> {namespace} ({t.max_gpus} GPUs)")

        print(f"\n{len(tenants)} tenant(s) reprovisioned")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
