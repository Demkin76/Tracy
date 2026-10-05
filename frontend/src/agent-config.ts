export type Configuration = {
  source_strategy_id?: string | null;
  source_version?: number | null;
  name: string;
  goal: string;
  risk_tolerance: "low" | "medium" | "high";
  forbidden: string[];
  market: string;
  symbols: string[];
  timeframe: string;
  starting_capital: number;
  change_note: string;
  strategy_config: {
    runner: string;
    lookback: number;
    exit_after_bars: number;
    threshold_bps: number;
    allocation_pct: number;
    fee_bps: number;
    slippage_bps: number;
  };
  guardrails: {
    max_position_size: number;
    max_trade_size: number;
    max_daily_loss: number;
    max_drawdown: number;
    allowed_tokens: string[];
    allowed_markets: string[];
    max_open_positions: number;
    human_approval_above: number;
  };
};

export const agentDefaults = (): Configuration => ({
  name: "",
  goal: "",
  risk_tolerance: "low",
  forbidden: ["leverage", "withdrawals", "short_selling"],
  market: "SOL/USDC",
  symbols: ["SOL", "USDC"],
  timeframe: "1h",
  starting_capital: 1000,
  change_note: "Reviewed agent intent",
  strategy_config: {
    runner: "mean_reversion",
    lookback: 3,
    exit_after_bars: 6,
    threshold_bps: 10,
    allocation_pct: 10,
    fee_bps: 10,
    slippage_bps: 8,
  },
  guardrails: {
    max_position_size: 300,
    max_trade_size: 200,
    max_daily_loss: 1,
    max_drawdown: 10,
    allowed_tokens: ["SOL", "USDC"],
    allowed_markets: ["SOL/USDC"],
    max_open_positions: 1,
    human_approval_above: 100,
  },
});
