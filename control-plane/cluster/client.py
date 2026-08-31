"""Thin wrapper around the Kubernetes Python client.

Every workload the control plane creates gets a `kestrel.dev/managed-by: kestrel`
label so ClusterClient never has to guess whether an object is one of ours.
The kwok toleration is always attached — it's a no-op on real nodes (no matching
taint), so job/deployment creation code doesn't need to branch on
simulated-vs-real hardware. That's the seam that lets a real GPU node work
later without touching this file.
"""

from __future__ import annotations

from typing import Any

from kubernetes import client, config

from schema.cluster import NodeInfo

MANAGED_BY_LABEL = {"kestrel.dev/managed-by": "kestrel"}
KWOK_TOLERATION = client.V1Toleration(
    key="kwok.x-k8s.io/node", operator="Exists", effect="NoSchedule"
)
GPU_RESOURCE = "nvidia.com/gpu"

# Verified directly against the Kueue release installed by deploy/kueue/install.sh
# (kueue:v0.19.1): v1beta2 is the storage version there (v1beta1 is still served for
# back-compat but storage=false). Re-check with:
#   kubectl get crd clusterqueues.kueue.x-k8s.io \
#     -o jsonpath='{range .spec.versions[*]}{.name}{" storage="}{.storage}{"\n"}{end}'
# if a Kueue upgrade ever changes it.
KUEUE_GROUP = "kueue.x-k8s.io"
KUEUE_VERSION = "v1beta2"
FAKE_GPU_NODE_LABEL = {"run.ai/simulated-gpu-node-pool": "default"}


class ClusterClient:
    def __init__(self, kubeconfig_path: str | None = None) -> None:
        if kubeconfig_path:
            config.load_kube_config(config_file=kubeconfig_path)
        else:
            config.load_kube_config()
        self.core = client.CoreV1Api()
        self.batch = client.BatchV1Api()
        self.apps = client.AppsV1Api()
        self.custom = client.CustomObjectsApi()

    @staticmethod
    def _ignore_conflict(exc: client.ApiException) -> None:
        if exc.status != 409:
            raise exc

    @staticmethod
    def _ignore_not_found(exc: client.ApiException) -> None:
        if exc.status != 404:
            raise exc

    def ensure_namespace(self, name: str) -> None:
        ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=name, labels=MANAGED_BY_LABEL))
        try:
            self.core.create_namespace(ns)
        except client.ApiException as e:
            self._ignore_conflict(e)

    def ensure_resource_quota(self, namespace: str, max_gpus: int, max_workloads: int) -> None:
        quota = client.V1ResourceQuota(
            metadata=client.V1ObjectMeta(
                name="kestrel-quota", namespace=namespace, labels=MANAGED_BY_LABEL
            ),
            spec=client.V1ResourceQuotaSpec(
                hard={
                    f"requests.{GPU_RESOURCE}": str(max_gpus),
                    "pods": str(max_workloads),
                }
            ),
        )
        try:
            self.core.create_namespaced_resource_quota(namespace=namespace, body=quota)
        except client.ApiException as e:
            self._ignore_conflict(e)

    def ensure_resource_flavor(self, name: str = "fake-gpu") -> None:
        body = {
            "apiVersion": f"{KUEUE_GROUP}/{KUEUE_VERSION}",
            "kind": "ResourceFlavor",
            "metadata": {"name": name, "labels": MANAGED_BY_LABEL},
            "spec": {"nodeLabels": FAKE_GPU_NODE_LABEL},
        }
        try:
            self.custom.create_cluster_custom_object(
                KUEUE_GROUP, KUEUE_VERSION, "resourceflavors", body
            )
        except client.ApiException as e:
            self._ignore_conflict(e)

    def ensure_cluster_queue(
        self, name: str, nominal_gpu_quota: int, flavor: str = "fake-gpu"
    ) -> None:
        body = {
            "apiVersion": f"{KUEUE_GROUP}/{KUEUE_VERSION}",
            "kind": "ClusterQueue",
            "metadata": {"name": name, "labels": MANAGED_BY_LABEL},
            "spec": {
                "namespaceSelector": {},
                "resourceGroups": [
                    {
                        "coveredResources": [GPU_RESOURCE],
                        "flavors": [
                            {
                                "name": flavor,
                                "resources": [
                                    {
                                        "name": GPU_RESOURCE,
                                        "nominalQuota": str(nominal_gpu_quota),
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }
        try:
            self.custom.create_cluster_custom_object(
                KUEUE_GROUP, KUEUE_VERSION, "clusterqueues", body
            )
        except client.ApiException as e:
            self._ignore_conflict(e)

    def ensure_local_queue(self, namespace: str, name: str, cluster_queue: str) -> None:
        body = {
            "apiVersion": f"{KUEUE_GROUP}/{KUEUE_VERSION}",
            "kind": "LocalQueue",
            "metadata": {"name": name, "namespace": namespace, "labels": MANAGED_BY_LABEL},
            "spec": {"clusterQueue": cluster_queue},
        }
        try:
            self.custom.create_namespaced_custom_object(
                KUEUE_GROUP, KUEUE_VERSION, namespace, "localqueues", body
            )
        except client.ApiException as e:
            self._ignore_conflict(e)

    def ensure_kueue_workload(
        self, name: str, namespace: str, queue_name: str, image: str, gpus: int
    ) -> None:
        """Create a Kueue Workload CR describing a resource ask, without any K8s Job.

        This is Kueue's manual-integration pattern: Kueue admits this Workload when
        the tenant's quota allows, and the reconcile loop creates the real Job only
        after admission — with the node already chosen by the active PlacementPolicy.
        The pod template here is never run; it exists so Kueue can compute quota.
        Only GPU is requested: Kueue refuses to admit a Workload asking for any
        resource the ClusterQueue doesn't cover, and ours covers nvidia.com/gpu only.
        """
        requests: dict[str, str] = {}
        if gpus > 0:
            requests[GPU_RESOURCE] = str(gpus)
        body: dict[str, Any] = {
            "apiVersion": f"{KUEUE_GROUP}/{KUEUE_VERSION}",
            "kind": "Workload",
            "metadata": {"name": name, "namespace": namespace, "labels": MANAGED_BY_LABEL},
            "spec": {
                "queueName": queue_name,
                "podSets": [
                    {
                        "name": "main",
                        "count": 1,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "main",
                                        "image": image,
                                        "resources": {"requests": requests},
                                    }
                                ],
                                "restartPolicy": "Never",
                            }
                        },
                    }
                ],
            },
        }
        try:
            self.custom.create_namespaced_custom_object(
                KUEUE_GROUP, KUEUE_VERSION, namespace, "workloads", body
            )
        except client.ApiException as e:
            self._ignore_conflict(e)

    def get_kueue_workload(self, name: str, namespace: str) -> dict[str, Any] | None:
        try:
            obj = self.custom.get_namespaced_custom_object(
                KUEUE_GROUP, KUEUE_VERSION, namespace, "workloads", name
            )
        except client.ApiException as e:
            if e.status == 404:
                return None
            raise
        return dict(obj)

    def is_kueue_workload_admitted(self, name: str, namespace: str) -> bool:
        obj = self.get_kueue_workload(name, namespace)
        if obj is None:
            return False
        status = obj.get("status") or {}
        if status.get("admission"):
            return True
        return any(
            c.get("type") == "Admitted" and c.get("status") == "True"
            for c in status.get("conditions", [])
        )

    def delete_kueue_workload(self, name: str, namespace: str) -> None:
        """Deleting the Workload is how Kueue learns it's done — that releases its
        quota reservation so the next queued item can be admitted."""
        try:
            self.custom.delete_namespaced_custom_object(
                KUEUE_GROUP, KUEUE_VERSION, namespace, "workloads", name
            )
        except client.ApiException as e:
            self._ignore_not_found(e)

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
        """Create the real K8s Job, pinned to target_node when placement chose one.

        Deliberately unlabeled for Kueue: admission already happened against the
        separately-created Workload CR (ensure_kueue_workload), and the queue-name
        label would invite Kueue's Job webhook to suspend this Job and hand node
        choice back to the default scheduler.
        """
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

    def create_deployment(
        self,
        name: str,
        namespace: str,
        image: str,
        port: int,
        gpus: int = 0,
        replicas: int = 1,
        target_node: str | None = None,
    ) -> None:
        resources = None
        if gpus > 0:
            resources = client.V1ResourceRequirements(limits={GPU_RESOURCE: str(gpus)})

        container = client.V1Container(
            name=name,
            image=image,
            ports=[client.V1ContainerPort(container_port=port)],
            resources=resources,
        )
        # node_name on the shared template pins EVERY replica to this node — the
        # placement accounting must budget gpus * replicas for one node.
        pod_spec = client.V1PodSpec(
            containers=[container],
            tolerations=[KWOK_TOLERATION],
            node_name=target_node,
        )
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={**MANAGED_BY_LABEL, "app": name}),
            spec=pod_spec,
        )
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=name, namespace=namespace, labels=MANAGED_BY_LABEL),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
                selector=client.V1LabelSelector(match_labels={"app": name}),
                template=template,
            ),
        )
        self.apps.create_namespaced_deployment(namespace=namespace, body=deployment)

        service = client.V1Service(
            metadata=client.V1ObjectMeta(name=name, namespace=namespace, labels=MANAGED_BY_LABEL),
            spec=client.V1ServiceSpec(
                selector={"app": name},
                ports=[client.V1ServicePort(port=port, target_port=port)],
            ),
        )
        self.core.create_namespaced_service(namespace=namespace, body=service)

    def delete_deployment(self, name: str, namespace: str) -> None:
        try:
            self.apps.delete_namespaced_deployment(
                name=name, namespace=namespace, propagation_policy="Foreground"
            )
        except client.ApiException as e:
            self._ignore_not_found(e)
        try:
            self.core.delete_namespaced_service(name=name, namespace=namespace)
        except client.ApiException as e:
            self._ignore_not_found(e)

    def get_deployment_status(self, name: str, namespace: str) -> str:
        dep = self.apps.read_namespaced_deployment_status(name=name, namespace=namespace)
        desired = dep.spec.replicas or 0
        ready = dep.status.ready_replicas or 0
        if desired == 0:
            return "stopped"
        if ready >= desired:
            return "running"
        return "pending"

    def delete_job(self, name: str, namespace: str) -> None:
        try:
            self.batch.delete_namespaced_job(
                name=name,
                namespace=namespace,
                propagation_policy="Foreground",
            )
        except client.ApiException as e:
            self._ignore_not_found(e)

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
