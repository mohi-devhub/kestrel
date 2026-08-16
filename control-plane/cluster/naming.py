"""Kubernetes/Kueue object names derived from a tenant slug.

Centralized here so tenant bootstrap (admin routes) and workload submission (jobs/endpoints
routes) can never drift apart on how a tenant's namespace or queue names are spelled.
"""


def tenant_namespace(slug: str) -> str:
    return f"tenant-{slug}"


def tenant_cluster_queue(slug: str) -> str:
    return f"cq-{slug}"


def tenant_local_queue(slug: str) -> str:
    return f"lq-{slug}"
