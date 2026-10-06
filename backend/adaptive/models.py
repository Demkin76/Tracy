from typing import Literal

from pydantic import Field, StrictBool, model_validator

from backend.actions.models import StrictModel
from backend.strategies.models import TradingGuardrails


class Program(StrictModel):
    kind: Literal["momentum", "mean_reversion", "sma_cross", "ema_cross"] = "momentum"
    lookback: int = Field(default=7, ge=2, le=100, strict=True)
    threshold_bps: float = Field(default=60, ge=1, le=2000)
    exit_after_bars: int = Field(default=12, ge=1, le=96, strict=True)
    fast: int = Field(default=5, ge=2, le=50, strict=True)
    slow: int = Field(default=20, ge=3, le=100, strict=True)

    @model_validator(mode="after")
    def coherent(self):
        if self.fast >= self.slow:
            raise ValueError("Fast SMA must be shorter than slow SMA")
        return self


class LearningConfig(StrictModel):
    expected_return_pct: float = Field(default=0.5, gt=0, le=20, allow_inf_nan=False)
    horizon_bars: int = Field(default=4, ge=1, le=96, strict=True)
    invalidation_pct: float = Field(default=-1.5, ge=-50, lt=0, allow_inf_nan=False)
    minimum_samples: int = Field(default=20, ge=3, le=1000, strict=True)


class Blueprint(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    intent: str = Field(min_length=10, max_length=2000)
    market: Literal["SOL/USDC", "BTC/USDC", "ETH/USDC"] = "BTC/USDC"
    timeframe: Literal["1h", "4h", "1d"] = "1h"
    capital: float = Field(default=1000, ge=100, le=1000000)
    allocation_pct: float = Field(default=10, gt=0, le=25)
    fee_bps: float = Field(default=10, ge=0, le=200)
    slippage_bps: float = Field(default=10, ge=0, le=500)
    program: Program = Field(default_factory=Program)
    guardrails: TradingGuardrails = Field(
        default_factory=lambda: TradingGuardrails(
            max_position_size=150,
            max_trade_size=150,
            max_daily_loss=0.5,
            max_drawdown=1.5,
            allowed_tokens=["BTC", "USDC"],
            allowed_markets=["BTC/USDC"],
            max_open_positions=1,
            human_approval_above=150,
        )
    )
    learning: LearningConfig = Field(default_factory=LearningConfig)
    pine_source: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def coherent(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Enter a strategy name")
        g = self.guardrails
        if g.allowed_markets != [self.market] or g.allowed_tokens != self.market.split("/"):
            raise ValueError("Permissions must match the selected market")
        if (
            not self.capital * self.allocation_pct / 100
            <= g.max_trade_size
            <= g.max_position_size
            <= self.capital
        ):
            raise ValueError("Entry allocation <= trade limit <= position limit <= capital is required")
        if g.max_open_positions != 1:
            raise ValueError("The devnet learning runner supports exactly one spot position")
        if self.capital * self.allocation_pct / 100 > g.human_approval_above:
            raise ValueError("Use an allocation inside your approved automatic trading allowance")
        return self


class PineImport(StrictModel):
    source: str = Field(min_length=1, max_length=10000)


class Experiment(StrictModel):
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    expected_revision: int = Field(ge=1, strict=True)
    period_start: int | None = Field(default=None, ge=0, le=4000000000, strict=True)
    training_bars: int = Field(default=576, ge=192, le=672, strict=True)
    validation_bars: int = Field(default=288, ge=96, le=288, strict=True)


class Review(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Publication(StrictModel):
    listed: StrictBool


class CloneBundle(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    mode: Literal["strategy", "bundle"] = "bundle"


class ForkStrategy(StrictModel):
    strategy_id: str
    version: int | None = Field(default=None, ge=1, strict=True)
    name: str = Field(min_length=1, max_length=100)


class StartReview(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_mode: Literal["frozen", "adaptive"] = "adaptive"
    acknowledged: StrictBool


class BuilderRequest(StrictModel):
    intent: str = Field(min_length=10, max_length=2000)
    draft: Blueprint
