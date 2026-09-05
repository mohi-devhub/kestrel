from pydantic import BaseModel


class NodeInfo(BaseModel):
    name: str
    ready: bool
    # kind leaves the control-plane node untainted, so it is schedulable unless
    # placement excludes it deliberately. Tenant work does not belong there.
    is_control_plane: bool = False
    gpu_capacity: int
    gpu_allocatable: int
    cpu_capacity: str
    memory_capacity: str


class NodeUsage(BaseModel):
    """A node with the control plane's own GPU accounting (not K8s allocatable —
    placements bypass kube-scheduler, so usage is tracked from workload state)."""

    name: str
    ready: bool
    gpu_total: int
    gpu_used: int
    gpu_free: int
    cpu_capacity: str
    memory_capacity: str
