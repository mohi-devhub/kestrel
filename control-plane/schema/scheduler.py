from pydantic import BaseModel


class PolicySwitchRequest(BaseModel):
    name: str


class ActivePolicyOut(BaseModel):
    name: str
