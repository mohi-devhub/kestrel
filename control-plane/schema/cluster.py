from pydantic import BaseModel


class NodeInfo(BaseModel):
    name: str
    ready: bool
    gpu_capacity: int
    gpu_allocatable: int
    cpu_capacity: str
    memory_capacity: str
