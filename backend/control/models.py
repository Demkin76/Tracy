import json
from typing import Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from backend.actions.models import Identifier, StrictModel


class Identity(StrictModel):
    agent_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    public_key: str
    description: str = Field(default="", max_length=1000)


class Intent(StrictModel):
    schema_version: Literal["tracy.intent/2"] = "tracy.intent/2"
    request_id: Identifier
    agent_id: Identifier
    task_id: Identifier
    action: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.]+$")
    resource_id: Identifier
    params: dict
    reason: str = Field(default="", max_length=500)
    timestamp: int = Field(ge=0, strict=True)
    signature: str = Field(max_length=200)

    @field_validator("params")
    @classmethod
    def bounded_json(cls, value):
        if len(json.dumps(value, allow_nan=False)) > 16384:
            raise ValueError("Intent parameters exceed 16 KiB")
        from backend.crypto.hashing import canonical_bytes

        canonical_bytes(value)
        return value

    def unsigned(self):
        return self.model_dump(exclude={"signature"})


class Lookup(StrictModel):
    domain: Literal["tracy.lookup/2"] = "tracy.lookup/2"
    agent_id: Identifier
    intent_id: Identifier
    timestamp: int = Field(ge=0, strict=True)
    signature: str = Field(max_length=200)


class Rule(StrictModel):
    action: str = Field(min_length=1, max_length=80)
    resource_id: Identifier
    allowed_targets: list[str] = Field(min_length=1, max_length=100)
    max_units_per_action: int = Field(ge=1, le=9_000_000_000_000_000, strict=True)
    daily_units: int = Field(ge=1, le=9_000_000_000_000_000, strict=True)
    require_approval: StrictBool = True


class Policy(StrictModel):
    rules: list[Rule] = Field(max_length=50)
    max_per_minute: int = Field(default=10, ge=1, le=1000, strict=True)
    max_denials_per_hour: int = Field(default=5, ge=1, le=1000, strict=True)
    review_new_targets: StrictBool = True
    approval_ttl_seconds: int = Field(default=900, ge=30, le=86400, strict=True)

    @model_validator(mode="after")
    def unique_rules(self):
        pairs = [(r.action, r.resource_id) for r in self.rules]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate action/resource rule")
        return self


class PolicyUpdate(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    policy: Policy


class TaskCreate(StrictModel):
    agent_id: Identifier
    purpose: str = Field(min_length=3, max_length=1000)
    allowed_resources: list[Identifier] = Field(min_length=1, max_length=50)
    allowed_actions: list[str] = Field(min_length=1, max_length=50)
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800, strict=True)


class Decision(StrictModel):
    decision: Literal["approve", "deny"]
    intent_hash: str = Field(min_length=64, max_length=64)
    policy_version: int = Field(ge=1, strict=True)
    note: str = Field(default="", max_length=500)
