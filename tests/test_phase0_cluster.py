"""Integration tests against the real `kestrel` kind cluster (Phase 0 acceptance).

Requires: `bash deploy/bootstrap.sh` has been run, and KUBECONFIG_PATH points at
deploy/kubeconfig/host.yaml (or the default kubeconfig has the kind-kestrel context).
"""

from pathlib import Path

import pytest

from cluster import ClusterClient

KUBECONFIG = str(Path(__file__).parent.parent / "deploy" / "kubeconfig" / "host.yaml")


@pytest.fixture(scope="module")
def cluster() -> ClusterClient:
    return ClusterClient(kubeconfig_path=KUBECONFIG)


def test_lists_fake_gpu_nodes(cluster: ClusterClient) -> None:
    nodes = cluster.list_nodes()
    gpu_nodes = [n for n in nodes if n.gpu_capacity > 0]

    assert len(gpu_nodes) == 4
    for node in gpu_nodes:
        assert node.ready
        assert node.gpu_capacity == 4
        assert node.gpu_allocatable == 4


def test_create_and_delete_job(cluster: ClusterClient) -> None:
    job_name = "phase0-smoke-test"
    namespace = "default"

    cluster.create_job(
        name=job_name,
        namespace=namespace,
        image="busybox",
        command=["sleep", "30"],
        gpus=1,
    )
    try:
        status = cluster.get_job_status(job_name, namespace)
        assert status in {"pending", "running"}
    finally:
        cluster.delete_job(job_name, namespace)
