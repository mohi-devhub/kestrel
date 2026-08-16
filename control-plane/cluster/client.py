"""Thin wrapper around the Kubernetes Python client.

Every workload the control plane creates gets a `foundry.dev/managed-by: foundry`
label so ClusterClient never has to guess whether an object is one of ours.
The kwok toleration is always attached — it's a no-op on real nodes (no matching
taint), so job/deployment creation code doesn't need to branch on
simulated-vs-real hardware. That's the seam that lets a real GPU node work
later without touching this file.
"""

from __future__ import annotations

from kubernetes import client, config

from schema.cluster import NodeInfo

MANAGED_BY_LABEL = {"foundry.dev/managed-by": "foundry"}
KWOK_TOLERATION = client.V1Toleration(
    key="kwok.x-k8s.io/node", operator="Exists", effect="NoSchedule"
)
GPU_RESOURCE = "nvidia.com/gpu"


class ClusterClient:
    def __init__(self, kubeconfig_path: str | None = None) -> None:
        if kubeconfig_path:
            config.load_kube_config(config_file=kubeconfig_path)
        else:
            config.load_kube_config()
        self.core = client.CoreV1Api()
        self.batch = client.BatchV1Api()

    def list_nodes(self) -> list[NodeInfo]:
        nodes = self.core.list_node()
        result = []
        for n in nodes.items:
            ready = any(
                c.type == "Ready" and c.status == "True" for c in (n.status.conditions or [])
            )
            capacity = n.status.capacity or {}
            allocatable = n.status.allocatable or {}
            result.append(
                NodeInfo(
                    name=n.metadata.name,
                    ready=ready,
                    gpu_capacity=int(capacity.get(GPU_RESOURCE, 0)),
                    gpu_allocatable=int(allocatable.get(GPU_RESOURCE, 0)),
                    cpu_capacity=str(capacity.get("cpu", "0")),
                    memory_capacity=str(capacity.get("memory", "0")),
                )
            )
        return result

    def create_job(
        self,
        name: str,
        namespace: str,
        image: str,
        command: list[str],
        gpus: int = 0,
        target_node: str | None = None,
    ) -> None:
        resources = None
        if gpus > 0:
            resources = client.V1ResourceRequirements(limits={GPU_RESOURCE: str(gpus)})

        container = client.V1Container(
            name=name,
            image=image,
            command=command,
            resources=resources,
        )
        pod_spec = client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            tolerations=[KWOK_TOLERATION],
            node_name=target_node,
        )
        job = client.V1Job(
            metadata=client.V1ObjectMeta(name=name, namespace=namespace, labels=MANAGED_BY_LABEL),
            spec=client.V1JobSpec(
                template=client.V1PodTemplateSpec(spec=pod_spec),
                backoff_limit=0,
            ),
        )
        self.batch.create_namespaced_job(namespace=namespace, body=job)

    def delete_job(self, name: str, namespace: str) -> None:
        self.batch.delete_namespaced_job(
            name=name,
            namespace=namespace,
            propagation_policy="Foreground",
        )

    def get_job_status(self, name: str, namespace: str) -> str:
        job = self.batch.read_namespaced_job_status(name=name, namespace=namespace)
        status = job.status
        if status.succeeded:
            return "succeeded"
        if status.failed:
            return "failed"
        if status.active:
            return "running"
        return "pending"
