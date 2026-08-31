from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster import ClusterClient
from config import settings
from db import get_db
from db.models import Workload
from scheduler.accounting import used_gpus_by_node
from schema.cluster import NodeUsage
from schema.workload import WorkloadOut

from ..deps import require_admin

router = APIRouter(prefix="/cluster", tags=["cluster"], dependencies=[Depends(require_admin)])


def _cluster_client() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


@router.get("/nodes", response_model=list[NodeUsage])
def cluster_nodes(db: Session = Depends(get_db)) -> list[NodeUsage]:
    running = db.execute(select(Workload).where(Workload.status == "running")).scalars().all()
    used = used_gpus_by_node(running)
    return [
        NodeUsage(
            name=n.name,
            ready=n.ready,
            gpu_total=n.gpu_capacity,
            gpu_used=used.get(n.name, 0),
            gpu_free=n.gpu_capacity - used.get(n.name, 0),
            cpu_capacity=n.cpu_capacity,
            memory_capacity=n.memory_capacity,
        )
        for n in _cluster_client().list_nodes()
    ]


@router.get("/workloads", response_model=list[WorkloadOut])
def cluster_workloads(db: Session = Depends(get_db)) -> list[Workload]:
    return list(db.execute(select(Workload)).scalars().all())
