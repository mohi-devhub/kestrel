"""Structural interface over the cluster operations the reconcile loop needs.

ClusterClient satisfies this without inheriting it; tests substitute an in-memory
fake so the reconcile logic is unit-testable without a kubeconfig.
"""

from __future__ import annotations

from typing import Protocol

from schema.cluster import NodeInfo


class ClusterPort(Protocol):
    def list_nodes(self) -> list[NodeInfo]: ...

    def create_job(
        self,
        name: str,
        namespace: str,
        image: str,
        command: list[str],
        gpus: int = 0,
        target_node: str | None = None,
    ) -> None: ...

    def create_deployment(
        self,
        name: str,
        namespace: str,
        image: str,
        port: int,
        gpus: int = 0,
        replicas: int = 1,
        target_node: str | None = None,
    ) -> None: ...

    def get_job_status(self, name: str, namespace: str) -> str: ...

    def is_kueue_workload_admitted(self, name: str, namespace: str) -> bool: ...

    def delete_kueue_workload(self, name: str, namespace: str) -> None: ...
