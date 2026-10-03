import math
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, field_validator
from solders.pubkey import Pubkey

LAMPORTS_PER_SOL = 1_000_000_000


def amount_number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Amount must be a finite JSON number")
    lamports = Decimal(str(value)) * LAMPORTS_PER_SOL
    if value <= 0 or value > 1_000_000 or lamports != lamports.to_integral_value():
        raise ValueError("Amount must be positive, at most 1,000,000 SOL, with at most 9 decimals")
    return value


SolAmount = Annotated[float, BeforeValidator(amount_number)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransferParams(StrictModel):
    to: str = Field(min_length=32, max_length=44)
    amount: SolAmount

    @field_validator("to")
    @classmethod
    def valid_address(cls, value: str) -> str:
        try:
            Pubkey.from_string(value)
        except ValueError as exc:
            raise ValueError("Invalid Solana recipient") from exc
        return value

    @property
    def lamports(self) -> int:
        return int(Decimal(str(self.amount)) * LAMPORTS_PER_SOL)


class ActionRequest(StrictModel):
    request_id: Identifier
    agent_id: Identifier
    action: str = Field(min_length=1, max_length=80)
    params: TransferParams
    timestamp: StrictInt = Field(ge=0, le=9_007_199_254_740_991)
    signature: str = Field(max_length=200)

    def unsigned(self) -> dict:
        return self.model_dump(exclude={"signature"})
