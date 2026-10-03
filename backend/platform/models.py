from typing import Literal

from pydantic import Field, StrictBool, field_validator

from backend.actions.models import StrictModel


class Publication(StrictModel):
    listed: StrictBool
    category: Literal["payouts", "automation", "research", "other"] = "payouts"
    tagline: str = Field(default="", max_length=160)
    disclose_history: StrictBool = False


class ShareProof(StrictModel):
    receipt_id: str = Field(max_length=80)
    expires_days: int = Field(default=7, ge=1, le=30)
    disclose_receipt: StrictBool


class PasswordChange(StrictModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class RecoveryIssue(StrictModel):
    current_password: str = Field(max_length=128)


class AccountRecovery(StrictModel):
    email: str = Field(max_length=254)
    recovery_code: str = Field(min_length=20, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower()


class ProfileEdit(StrictModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()
