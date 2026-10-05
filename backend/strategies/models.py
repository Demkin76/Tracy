from typing import Literal

from pydantic import Field, StrictBool, model_validator

from backend.actions.models import Identifier, StrictModel


class TradingGuardrails(StrictModel):
    max_position_size: float = Field(default=10000, gt=0, le=100000000, allow_inf_nan=False)
    max_trade_size: float = Field(default=5000, gt=0, le=100000000, allow_inf_nan=False)
    max_daily_loss: float = Field(default=5, gt=0, le=100, allow_inf_nan=False)
    max_drawdown: float = Field(default=20, gt=0, le=100, allow_inf_nan=False)
    allowed_tokens: list[Literal["SOL", "BTC", "ETH", "USDC"]] = Field(
        default_factory=lambda: ["SOL", "USDC"], min_length=1, max_length=4
    )
    allowed_markets: list[Literal["SOL/USDC", "BTC/USDC", "ETH/USDC"]] = Field(
        default_factory=lambda: ["SOL/USDC"], min_length=1, max_length=3
    )
    max_open_positions: int = Field(default=1, ge=1, le=10, strict=True)
    human_approval_above: float = Field(default=5000, ge=0, le=100000000, allow_inf_nan=False)


class RunnerConfig(StrictModel):
    runner: Literal["momentum", "mean_reversion", "buy_hold"] = "momentum"
    lookback: int = Field(default=3, ge=2, le=20, strict=True)
    exit_after_bars: int = Field(default=6, ge=1, le=48, strict=True)
    threshold_bps: float = Field(default=10, ge=0, le=5000, allow_inf_nan=False)
    allocation_pct: float = Field(default=40, gt=0, le=90, allow_inf_nan=False)
    fee_bps: float = Field(default=10, ge=0, le=200, allow_inf_nan=False)
    slippage_bps: float = Field(default=8, ge=0, le=500, allow_inf_nan=False)


class VersionInput(StrictModel):
    market: Literal["SOL/USDC", "BTC/USDC", "ETH/USDC"] = "SOL/USDC"
    symbols: list[str] = Field(default_factory=lambda: ["SOL", "USDC"], min_length=2, max_length=2)
    timeframe: Literal["1h", "4h", "1d"] = "1h"
    starting_capital: float = Field(default=10000, ge=100, le=10000000, allow_inf_nan=False)
    strategy_config: RunnerConfig = Field(default_factory=RunnerConfig)
    guardrails: TradingGuardrails = Field(default_factory=TradingGuardrails)
    change_note: str = Field(default="Initial version", min_length=1, max_length=1000)

    @model_validator(mode="after")
    def symbols_match(self):
        if self.symbols != self.market.split("/"):
            raise ValueError("Symbols must match the selected market in base/quote order")
        return self


class StrategyCreate(VersionInput):
    agent_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)


class NewVersion(VersionInput):
    expected_version: int = Field(ge=1, strict=True)


class TestRequest(StrictModel):
    dataset: Literal["historical"] = "historical"
    period_start: int | None = Field(default=None, ge=0, le=4000000000, strict=True)
    bars: int = Field(default=96, ge=30, le=240, strict=True)


class Deploy(StrictModel):
    expected_version: int = Field(ge=1, strict=True)
    mode: Literal["paper"] = "paper"


class Lifecycle(StrictModel):
    status: Literal["PAUSED", "LIVE", "ARCHIVED"]
    expected_version: int = Field(ge=1, strict=True)


class Advance(StrictModel):
    expected_step: int = Field(ge=0, strict=True)
    steps: int = Field(default=12, ge=1, le=48, strict=True)


class Publish(StrictModel):
    listed: StrictBool


class Clone(StrictModel):
    agent_id: Identifier
    name: str = Field(min_length=1, max_length=100)
