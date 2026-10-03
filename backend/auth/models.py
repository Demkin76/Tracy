import re
from typing import Literal

from pydantic import Field, field_validator

from backend.actions.models import StrictModel


class Login(StrictModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class Signup(Login):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class CreateApiKey(StrictModel):
    scope: Literal["manage", "read"] = "manage"
    name: str = Field(min_length=1, max_length=80)
