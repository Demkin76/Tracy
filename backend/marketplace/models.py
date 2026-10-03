from typing import Literal

from pydantic import Field, StrictBool, model_validator

from backend.actions.models import Identifier, StrictModel, TransferParams
from backend.policies.engine import Policy

Kind = Literal["batch_payout", "scheduled_payout"]


class Offer(StrictModel):
    kind: Kind
    enabled: StrictBool = True


class Plan(StrictModel):
    transfers: list[TransferParams] = Field(min_length=1, max_length=20)
    interval_seconds: int = Field(default=3600, ge=60, le=2592000, strict=True)
    max_cycles: int = Field(default=1, ge=1, le=100, strict=True)


class Install(StrictModel):
    request_id: Identifier
    source_agent_id: Identifier
    expected_version: int = Field(ge=1, strict=True)
    name: str = Field(min_length=1, max_length=100)
    policy: Policy
    plan: Plan

    @model_validator(mode="after")
    def valid_plan(self):
        if not self.name.strip():
            raise ValueError("Name cannot be blank")
        return self


class EditPlan(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    plan: Plan


class RunRequest(StrictModel):
    request_id: Identifier
