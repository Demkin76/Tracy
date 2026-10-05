from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from backend.actions.models import StrictModel


class Order(StrictModel):
    strategy_version: int = Field(ge=1, strict=True)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    requested_price: float = Field(gt=0, le=10000000, allow_inf_nan=False)
    max_slippage_bps: float = Field(default=100, ge=0, le=1000, allow_inf_nan=False)

    @field_validator("quantity")
    @classmethod
    def precision(cls, value):
        units = Decimal(str(value)) * 100000000
        if units != units.to_integral_value():
            raise ValueError("Quantity supports at most 8 decimals")
        return value


class QuoteRequest(StrictModel):
    domain: Literal["tracy.quote/3"] = "tracy.quote/3"
    agent_id: str = Field(min_length=1, max_length=100)
    strategy_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    timestamp: int = Field(ge=0, strict=True)
    signature: str = Field(max_length=200)
