from pydantic import Field, StrictBool, field_validator

from backend.actions.models import Identifier, StrictModel
from backend.crypto.signatures import decode_base64
from backend.policies.engine import Policy


class RegisterAgent(StrictModel):
    agent_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    public_key: str
    policy: Policy

    @field_validator("public_key")
    @classmethod
    def valid_public_key(cls, value):
        decode_base64(value, 32)
        return value

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class AgentProfile(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=1000)


class AgentStatus(StrictModel):
    active: StrictBool


class UpdatePolicy(StrictModel):
    expected_version: int = Field(ge=1, strict=True)
    policy: Policy
