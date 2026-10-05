import React, { useEffect, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BarChart3,
  CheckCheck,
  ShieldCheck,
  FlaskConical,
  GitBranch,
  Play,
  Plus,
  RefreshCw,
  Pause,
  ArrowUpRight,
} from "lucide-react";
import { HelpLink } from "./Copilot";
import canonicalize from "canonicalize";
import { api, download } from "./api";
import { useApp } from "./app-context";
import { ErrorNotice, err, Status, when } from "./PublicPages";

type MarketSource = {
  provider: string;
  market: string;
  timeframe: string;
  period_start: number;
  period_end: number;
  fetched_at: number;
  snapshot_id: string;
};
function DataSource({
  source,
  label,
  exportUrl,
}: {
  source?: MarketSource | null;
  label: string;
  exportUrl?: string;
}) {
  if (!source) return null;
  return (
    <div className="market-source">
      <strong>
        {label} · {source.provider} · {source.market}
      </strong>
      <span>
        {new Date(source.period_start * 1000).toLocaleString()} —{" "}
        {new Date(source.period_end * 1000).toLocaleString()} ·{" "}
        {source.timeframe} candles
      </span>
      <small>
        Retrieved {new Date(source.fetched_at * 1000).toLocaleString()} ·
        snapshot {source.snapshot_id.slice(0, 16)}
      </small>
      <details className="source-details">
        <summary>Source details & exact candles</summary>
        <p>
          Binance Spot · closed candles · UTC start{" "}
          {new Date(source.period_start * 1000).toISOString()} · UTC end{" "}
          {new Date(source.period_end * 1000).toISOString()}
        </p>
        <code>{source.snapshot_id}</code>
        {exportUrl && (
          <p>
            <a href={exportUrl} target="_blank" rel="noreferrer">
              Download candles & source metadata
            </a>
          </p>
        )}
        <HelpLink topic="data" />
      </details>
    </div>
  );
}
type Curve = { timestamp: number | null; equity: number };
type Metrics = {
  pnl: number;
  return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  max_drawdown: number;
  current_drawdown: number;
  win_rate: number | null;
  average_win: number | null;
  average_loss: number | null;
  profit_factor: number | null;
  profit_factor_note: string | null;
  trade_count: number;
  closed_trade_count: number;
  fees: number;
  slippage: number;
  cash: number;
  position_quantity: number;
  equity: number;
  equity_curve: Curve[];
  recent_closed_count: number;
};
type Health = {
  status: string;
  score: number | null;
  confidence: string;
  sample_size: number;
  components: Record<
    string,
    { weight: number; score: number; formula: string }
  >;
  reasons: { kind: string; severity: string; message: string }[];
};
type Performance = {
  market_data?: MarketSource | null;
  replay_market_data?: MarketSource | null;
  live: Metrics;
  backtest: Metrics | null;
  backtest_return: number | null;
  live_return: number | null;
  performance_gap: number | null;
  verified_trades: number;
  baseline_test_id: string | null;
  comparison_note: string;
  regime: {
    status: string;
    message: string;
    note?: string;
    current?: {
      price: number;
      volatility: number;
      volume: number;
      trend: string;
    };
    reference_volatility?: number;
  };
  deployment: null | {
    deployment_id: string;
    step: number;
    status: string;
    runner_public_key: string;
  };
  track_record_start: number | null;
  track_record_end: number | null;
};
type Config = {
  runner: string;
  lookback: number;
  exit_after_bars: number;
  threshold_bps: number;
  allocation_pct: number;
  fee_bps: number;
  slippage_bps: number;
};
type Risk = {
  max_position_size: number;
  max_trade_size: number;
  max_daily_loss: number;
  max_drawdown: number;
  allowed_tokens: string[];
  allowed_markets: string[];
  max_open_positions: number;
  human_approval_above: number;
};
type Version = {
  market: string;
  symbols: string[];
  timeframe: string;
  starting_capital: number;
  strategy_config: Config;
  guardrails: Risk;
  change_note: string;
};
export type Strategy = Version & {
  onboarding_plan_id?: string | null;
  strategy_id: string;
  agent_id: string;
  agent_name: string;
  name: string;
  description: string;
  version: number;
  current_version: number;
  status: string;
  listed: boolean;
  agent_listed: boolean;
  created_at: number;
  performance: Performance;
  health: Health;
  versions: { version: number; created_at: number; change_note: string }[];
};
type Trade = {
  trade_id: string;
  intent_id: string;
  strategy_version: number;
  side: string;
  quantity: number;
  requested_price: number;
  executed_price: number;
  fee: number;
  timestamp: number;
  market: string;
};
type Test = {
  test_id: string;
  strategy_version: number;
  dataset: string;
  mode: string;
  metrics: Metrics;
  started_at: number;
  market_period_start: number;
  market_period_end: number;
};
type Alert = {
  alert_id: string;
  strategy_id: string;
  strategy_name: string;
  version: number;
  kind: string;
  severity: string;
  message: string;
  created_at: number;
  acknowledged: number;
};
type TradingIntent = {
  intent_id: string;
  strategy_id: string;
  intent_hash: string;
  policy_version: number;
  status: string;
  reason: string;
  request: { reason: string; params: Record<string, unknown> };
  policy: Risk;
  decision: unknown;
  approval: unknown;
  receipt: null | { trade_id: string };
  approval_expires_at: number;
};

const num = (n: number | null | undefined, d = 2) =>
  n == null
    ? "—"
    : n.toLocaleString("en", {
        maximumFractionDigits: d,
        minimumFractionDigits: d,
      });
const pct = (n: number | null | undefined) =>
  n == null ? "—" : (n > 0 ? "+" : "") + num(n) + "%";
const money = (n: number | null | undefined) =>
  n == null ? "—" : "$" + num(n);
const tone = (n: number | null | undefined) =>
  n == null ? "" : n < 0 ? "negative" : "positive";
const post = (body: unknown = {}, method = "POST") => ({
  method,
  body: JSON.stringify(body),
});
export function useRemote<T>(path: string) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState("");
  async function reload() {
    try {
      const r = await api<T>(path);
      setData(r);
      setError("");
      return r;
    } catch (e) {
      setError(err(e));
      return null;
    }
  }
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const value = await api<T>(path);
        if (active) {
          setData(value);
          setError("");
        }
      } catch (e) {
        if (active) setError(err(e));
      }
    };
    setData(null);
    void refresh();
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [path]);
  return { data, error, reload, setError };
}
function Json({ value }: { value: unknown }) {
  return <pre className="control-json">{JSON.stringify(value, null, 2)}</pre>;
}
function PaperNote() {
  return (
    <div className="paper-note">
      <span className="mode-chip">PAPER / EXCHANGE DATA</span> Recorded market
      prices, simulated fills and signed ledger evidence. No real funds are
      traded.
    </div>
  );
}
function Heading({
  title,
  eyebrow = "STRATEGY LIFECYCLE",
  text,
  children,
}: {
  title: string;
  eyebrow?: string;
  text?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        {text && <p>{text}</p>}
      </div>
      {children}
    </div>
  );
}
function Metric({
  label,
  value,
  note,
  className = "",
}: {
  label: string;
  value: string;
  note?: string;
  className?: string;
}) {
  return (
    <div className="metric-v3">
      <span>{label}</span>
      <strong className={className}>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  );
}
function CurveChart({
  live,
  backtest,
  capital,
}: {
  live: Curve[];
  backtest?: Curve[];
  capital: number;
}) {
  const a = live.map((p) => (p.equity / capital - 1) * 100),
    b = (backtest || []).map((p) => (p.equity / capital - 1) * 100);
  const min = Math.min(0, ...a, ...b),
    max = Math.max(1, ...a, ...b),
    range = max - min || 1;
  const points = (xs: number[]) =>
    xs
      .map(
        (y, i) =>
          `${38 + (i / Math.max(1, xs.length - 1)) * 704},${190 - ((y - min) / range) * 154}`,
      )
      .join(" ");
  return (
    <div className="curve-wrap">
      <div className="chart-legend">
        <span className="live-key">
          {live.length > 1
            ? "Your agent: paper replay"
            : "Your agent: no replay observations yet"}
        </span>
        <span className="test-key">Strategy backtest (before deployment)</span>
        <small>Normalized progress · return %</small>
      </div>
      <svg
        viewBox="0 0 780 226"
        role="img"
        aria-label="Paper replay and backtest return curves, normalized by observation progress"
      >
        {[0, 1, 2, 3].map((i) => (
          <g key={i}>
            <line
              x1="38"
              x2="742"
              y1={36 + i * 51.3}
              y2={36 + i * 51.3}
              stroke="var(--border)"
            />
            <text x="0" y={40 + i * 51.3} fill="var(--muted)" fontSize="10">
              {num(max - (i * range) / 3, 1)}
            </text>
          </g>
        ))}
        {b.length > 1 && (
          <polyline
            points={points(b)}
            fill="none"
            stroke="#777777"
            strokeWidth="2"
            strokeDasharray="5 5"
          />
        )}
        {a.length > 1 && (
          <polyline
            points={points(a)}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="3"
            strokeLinejoin="round"
          />
        )}
        <text x="38" y="218" fill="var(--muted)" fontSize="11">
          Start
        </text>
        <text x="710" y="218" fill="var(--muted)" fontSize="11">
          Latest
        </text>
      </svg>
      <small>
        Separate recorded market periods; curves compare progress, not matching
        calendar dates.
      </small>
    </div>
  );
}
function HealthPanel({ health }: { health: Health }) {
  return (
    <section className="panel health-panel">
      <div className="section-heading">
        <h2>Strategy Health</h2>
        <HelpLink topic="health" />
        <Status value={health.status} />
      </div>
      <div className="health-number">
        {health.score ?? "—"}
        <span>/ 100</span>
      </div>
      <p className="muted">{health.confidence}</p>
      {health.reasons.length ? (
        <ul className="health-reasons">
          {health.reasons.map((r) => (
            <li key={r.kind}>{r.message}</li>
          ))}
        </ul>
      ) : (
        <p className="health-reasons">
          No threshold breach in the available sample.
        </p>
      )}
      <details>
        <summary>
          Why {health.score ?? "no score yet"}? View formula & breakdown
        </summary>
        {Object.entries(health.components).map(([k, c]) => (
          <div className="score-row" key={k}>
            <span>
              {k.replaceAll("_", " ").replaceAll("live", "paper")} ·{" "}
              {c.weight * 100}%
            </span>
            <b>
              {health.score == null
                ? "Insufficient observations"
                : num(c.score, 1)}
            </b>
            {health.score != null && <progress max="100" value={c.score} />}
            <code>{c.formula}</code>
          </div>
        ))}
        <p>
          Weighted sum of these five components. Requires 5 closed trades and a
          backtest. Diagnostic only, not a prediction.
        </p>
      </details>
    </section>
  );
}
export function StrategyCard({
  s,
  publicView = false,
}: {
  s: Strategy;
  publicView?: boolean;
}) {
  const p = s.performance;
  return (
    <article className="strategy-card">
      <div className="card-top">
        <span className="mode-chip">{s.market} · PAPER</span>
        <Status value={s.health.status} />
      </div>
      <Link
        to={
          publicView
            ? "/exchange/strategies/" + s.strategy_id
            : "/strategies/" + s.strategy_id
        }
      >
        <h2>
          {publicView ? s.agent_name : s.name}{" "}
          <span className="version-tag">v{s.version}</span>
        </h2>
      </Link>
      <p className="muted">
        {publicView ? s.name : s.agent_name} ·{" "}
        {s.strategy_config.runner.replaceAll("_", " ")}
      </p>
      <div className="card-metrics">
        <div>
          <span>Paper return</span>
          <strong className={tone(p.live_return)}>
            {p.verified_trades ? pct(p.live_return) : "—"}
          </strong>
        </div>
        <div>
          <span>Max drawdown</span>
          <strong>
            {p.verified_trades ? num(p.live.max_drawdown) + "%" : "—"}
          </strong>
        </div>
        <div>
          <span>Win rate</span>
          <strong>
            {p.live.win_rate == null ? "—" : num(p.live.win_rate, 1) + "%"}
          </strong>
        </div>
      </div>
      <div className="track-row">
        <span>
          Health <b>{s.health.score ?? "—"}/100</b>
        </span>
        <span>{p.verified_trades} verified paper fills</span>
      </div>
      <p className="muted">
        Track record:{" "}
        {p.track_record_start
          ? new Date(p.track_record_start * 1000).toLocaleDateString() +
            " – " +
            new Date(p.track_record_end! * 1000).toLocaleDateString()
          : "No executed trades"}
      </p>
      <div className="card-actions">
        <Link
          to={publicView ? "/a/" + s.agent_id : "/strategies/" + s.strategy_id}
        >
          {publicView ? "View agent" : "Open strategy"}{" "}
          <ArrowUpRight size={14} />
        </Link>
        <Link
          className="secondary"
          to={
            publicView
              ? "/agents/new?source=" + s.strategy_id + "&version=" + s.version
              : "/strategies/" + s.strategy_id
          }
        >
          {publicView ? "Test with my limits" : "Test / Monitor"}{" "}
          <ArrowRight size={14} />
        </Link>
      </div>
    </article>
  );
}

export function LifecycleOverview({ mode = "Overview" }: { mode?: string }) {
  const { data, error, reload } = useRemote<{ items: Strategy[] }>(
    "/strategies",
  );
  const [showArchived, setShowArchived] = useState(false);
  const alertData = useRemote<{ items: Alert[] }>("/degradation/alerts");
  if (!data)
    return (
      <>
        <Heading title={mode} />
        <ErrorNotice error={error} />
        <p>Loading strategies…</p>
      </>
    );
  const visible = data.items.filter(
    (s) => showArchived || s.status !== "ARCHIVED",
  );
  const active = visible.filter(
      (s) => s.performance.deployment && s.status !== "ARCHIVED",
    ),
    pnl = active.reduce((n, s) => n + s.performance.live.pnl, 0);
  const scored = visible.filter((s) => s.health.score != null),
    avg = scored.length
      ? scored.reduce((n, s) => n + s.health.score!, 0) / scored.length
      : null;
  const focus = active.find((s) => s.health.reasons.length) || active[0],
    alerts = alertData.data?.items.filter((a) => !a.acknowledged) || [];
  return (
    <>
      <Heading
        title={mode === "Overview" ? "My trading workspace" : mode}
        text="Follow your personal paper instances and the strategies behind them."
      >
        <Link className="primary" to="/">
          <ArrowRight size={16} /> Explore agents
        </Link>
      </Heading>
      <PaperNote />
      <ErrorNotice error={error || alertData.error} />
      <div className="lifecycle-ribbon">
        {[
          "Discover",
          "Compare evidence",
          "Test your limits",
          "Review & deploy",
          "Monitor",
          "Verify",
        ].map((x, i) => (
          <span key={x}>
            <i>{String(i + 1).padStart(2, "0")}</i>
            {x}
          </span>
        ))}
      </div>
      <div className="metrics-v3">
        <Metric
          label="Portfolio PnL · paper"
          value={money(pnl)}
          className={tone(pnl)}
          note="Current versions · separate virtual accounts"
        />
        <Metric
          label="Strategy health"
          value={avg == null ? "—" : num(avg, 0) + " / 100"}
          note={scored.length + " strategies with sufficient samples"}
        />
        <Metric
          label="Active deployments"
          value={String(
            data.items.filter((s) => ["LIVE", "DEGRADED"].includes(s.status))
              .length,
          )}
          note="Owner-controlled paper replay"
        />
        <Metric
          label="Open alerts"
          value={String(alerts.length)}
          note="Risk, performance and execution"
        />
      </div>
      {focus ? (
        <div className="lifecycle-grid">
          <section className="panel chart-panel">
            <div className="section-heading">
              <div>
                <h2>
                  {focus.name}{" "}
                  <span className="version-tag">v{focus.version}</span>
                </h2>
                <p className="muted">Recent performance</p>
              </div>
              <Link to={"/strategies/" + focus.strategy_id}>
                Open strategy →
              </Link>
            </div>
            <div className="gap-row">
              <Metric
                label="Paper replay return"
                value={pct(focus.performance.live_return)}
                className={tone(focus.performance.live_return)}
              />
              <Metric
                label="Backtest"
                value={pct(focus.performance.backtest_return)}
              />
              <Metric
                label="Gap"
                value={num(focus.performance.performance_gap) + " pp"}
                className={tone(focus.performance.performance_gap)}
              />
              <Metric
                label="Current drawdown"
                value={num(focus.performance.live.current_drawdown) + "%"}
              />
            </div>
            <CurveChart
              live={focus.performance.live.equity_curve}
              backtest={focus.performance.backtest?.equity_curve}
              capital={focus.starting_capital}
            />
          </section>
          <HealthPanel health={focus.health} />
        </div>
      ) : (
        <section className="panel editor">
          <h2>Choose an agent from the marketplace</h2>
          <p>
            Compare its public results and evidence, test its strategy with your
            limits, then review a personal paper instance.
          </p>
          <Link className="primary" to="/">
            Explore agents →
          </Link>
          <p>
            Developing your own agent?{" "}
            <Link to="/developers">Open developer studio →</Link>
          </p>
        </section>
      )}
      <div className="section-heading">
        <h2>Your strategies</h2>
        <label className="archive-filter">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />{" "}
          Show archived
        </label>
        <button className="text-button" onClick={() => void reload()}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      <div className="strategy-grid">
        {visible.map((s) => (
          <StrategyCard key={s.strategy_id} s={s} />
        ))}
      </div>
      <section className="panel alerts-preview">
        <div className="section-heading">
          <h2>What needs your attention</h2>
          <Link to="/degradation">All alerts →</Link>
        </div>
        {alerts.slice(0, 4).map((a) => (
          <Link
            className="alert-row"
            to={"/strategies/" + a.strategy_id}
            key={a.alert_id}
          >
            <Status value={a.severity} />
            <span>
              <b>
                {a.strategy_name} · v{a.version}
              </b>
              {a.message}
            </span>
            <ArrowRight size={16} />
          </Link>
        ))}
        {!alerts.length && <p className="muted">No unacknowledged alerts.</p>}
      </section>
    </>
  );
}
const defaults = (): Version => ({
  market: "SOL/USDC",
  symbols: ["SOL", "USDC"],
  timeframe: "1h",
  starting_capital: 10000,
  strategy_config: {
    runner: "momentum",
    lookback: 3,
    exit_after_bars: 6,
    threshold_bps: 10,
    allocation_pct: 40,
    fee_bps: 10,
    slippage_bps: 8,
  },
  guardrails: {
    max_position_size: 10000,
    max_trade_size: 5000,
    max_daily_loss: 5,
    max_drawdown: 20,
    allowed_tokens: ["SOL", "USDC"],
    allowed_markets: ["SOL/USDC"],
    max_open_positions: 1,
    human_approval_above: 5000,
  },
  change_note: "Initial version",
});
function VersionFields({
  value,
  setValue,
}: {
  value: Version;
  setValue: (v: Version) => void;
}) {
  const config = (k: keyof Config, v: string | number) =>
    setValue({
      ...value,
      strategy_config: { ...value.strategy_config, [k]: v },
    });
  const risk = (k: keyof Risk, v: number | string[]) =>
    setValue({ ...value, guardrails: { ...value.guardrails, [k]: v } });
  return (
    <>
      <div className="form-grid">
        <label>
          Market
          <select
            value={value.market}
            onChange={(e) =>
              setValue({
                ...value,
                market: e.target.value,
                symbols: e.target.value.split("/"),
                guardrails: {
                  ...value.guardrails,
                  allowed_markets: [e.target.value],
                  allowed_tokens: e.target.value.split("/"),
                },
              })
            }
          >
            {["SOL/USDC", "BTC/USDC", "ETH/USDC"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
        <label>
          Timeframe
          <select
            value={value.timeframe}
            onChange={(e) => setValue({ ...value, timeframe: e.target.value })}
          >
            {["1h", "4h", "1d"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
        <label>
          Starting capital · virtual USDC
          <input
            type="number"
            min="100"
            max="10000000"
            required
            value={value.starting_capital}
            onChange={(e) =>
              setValue({ ...value, starting_capital: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Strategy runner
          <select
            value={value.strategy_config.runner}
            onChange={(e) => config("runner", e.target.value)}
          >
            <option value="momentum">Momentum rules</option>
            <option value="mean_reversion">Mean reversion rules</option>
            <option value="buy_hold">Buy and hold</option>
          </select>
        </label>
      </div>
      <p className="form-help">
        You choose the rules. Tracy tests them against recorded exchange data;
        it does not recommend or optimize a strategy.
      </p>
      <details className="form-details" open>
        <summary>Runner parameters</summary>
        <div className="form-grid">
          {(
            [
              ["lookback", "Lookback bars", 2, 20],
              ["exit_after_bars", "Exit after bars", 1, 48],
              ["threshold_bps", "Signal threshold · bps", 0, 5000],
              ["allocation_pct", "Capital per entry · %", 1, 90],
              ["fee_bps", "Fee per fill · bps", 0, 200],
              ["slippage_bps", "Execution slippage · bps", 0, 500],
            ] as const
          ).map(([k, label, min, max]) => (
            <label key={k}>
              {label}
              <input
                required
                type="number"
                min={min}
                max={max}
                value={value.strategy_config[k]}
                onChange={(e) => config(k, Number(e.target.value))}
              />
            </label>
          ))}
        </div>
      </details>
      <details className="form-details" open>
        <summary>Trading guardrails</summary>
        <div className="form-grid">
          {(
            [
              ["max_trade_size", "Max trade · USDC"],
              ["max_position_size", "Max position · USDC"],
              ["max_daily_loss", "Max daily loss · %"],
              ["max_drawdown", "Max drawdown · %"],
              ["max_open_positions", "Max open positions"],
              ["human_approval_above", "Human approval above · USDC"],
            ] as const
          ).map(([k, label]) => (
            <label key={k}>
              {label}
              <input
                type="number"
                required
                min={k === "human_approval_above" ? 0 : 0.01}
                step="any"
                value={value.guardrails[k]}
                onChange={(e) => risk(k, Number(e.target.value))}
              />
            </label>
          ))}
        </div>
        <p className="form-help">
          Allowed market: {value.guardrails.allowed_markets.join(", ")}. Allowed
          tokens: {value.guardrails.allowed_tokens.join(", ")}. One spot market
          per version; no leverage or shorting.
        </p>
      </details>
      <label>
        Change note
        <input
          required
          maxLength={1000}
          value={value.change_note}
          onChange={(e) => setValue({ ...value, change_note: e.target.value })}
        />
      </label>
    </>
  );
}
export function StrategyCreatePage() {
  const { agents } = useApp(),
    navigate = useNavigate(),
    [search] = useSearchParams(),
    source = search.get("source");
  const [value, setValue] = useState(defaults),
    [agent, setAgent] = useState(""),
    [name, setName] = useState(""),
    [description, setDescription] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    if (source)
      void api<Strategy>("/public/trading/strategies/" + source)
        .then((s) => {
          setValue({
            ...s,
            change_note: "Copied " + s.strategy_id + " v" + s.version,
          });
          setName(s.name + " · my test");
          setDescription(s.description);
        })
        .catch((e) => setError(err(e)));
  }, [source]);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = {
        ...Object.fromEntries(
          Object.keys(defaults()).map((k) => [k, value[k as keyof Version]]),
        ),
        agent_id: agent || agents[0]?.agent_id,
        name,
        description,
      };
      const s = await api<Strategy>("/strategies", post(payload));
      navigate("/strategies/" + s.strategy_id);
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title={
          source ? "Test this strategy in your workspace" : "Create a strategy"
        }
        text="Configuration changes create new versions. Historical results remain attached to the version that produced them."
      />
      <PaperNote />
      <ErrorNotice error={error} />
      <form className="panel editor strategy-editor" onSubmit={submit}>
        <label>
          Strategy name
          <input
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. SOL Momentum"
          />
        </label>
        <label>
          Agent identity
          <select
            required
            value={agent || agents[0]?.agent_id || ""}
            onChange={(e) => setAgent(e.target.value)}
          >
            <option value="" disabled>
              Select your agent
            </option>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        {!agents.length && (
          <Link className="secondary" to="/control">
            Register an agent first →
          </Link>
        )}
        <label>
          Description
          <textarea
            maxLength={2000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <VersionFields value={value} setValue={setValue} />
        <button className="primary" disabled={busy || !agents.length}>
          {busy ? "Creating…" : "Create strategy"}
        </button>
      </form>
    </>
  );
}

function TradeTable({
  items,
  publicView = false,
}: {
  items: Trade[];
  publicView?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Market / time</th>
            <th>Version</th>
            <th>Side</th>
            <th>Requested → fill</th>
            <th>Quantity</th>
            <th>Fee</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <tr key={t.trade_id}>
              <td>
                {t.market}
                <small>{when(t.timestamp)}</small>
              </td>
              <td>v{t.strategy_version}</td>
              <td>
                <Status value={t.side} />
              </td>
              <td>
                {num(t.requested_price)} → {num(t.executed_price)}
              </td>
              <td>{num(t.quantity, 6)}</td>
              <td>{num(t.fee, 4)}</td>
              <td>
                <Link
                  className="proof-link"
                  to={
                    (publicView ? "/exchange/proofs/" : "/trades/") +
                    t.trade_id +
                    (publicView ? "" : "/proof")
                  }
                >
                  Open proof →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!items.length && (
        <div className="empty">No fills for this version yet.</div>
      )}
    </div>
  );
}
export function StrategyDetail({
  publicView = false,
}: {
  publicView?: boolean;
}) {
  const [showPublication, setShowPublication] = useState(false);
  const [sectionParams] = useSearchParams();
  useEffect(() => {
    if (sectionParams.get("publish") === "1") setShowPublication(true);
  }, [sectionParams]);
  const requestedTab = sectionParams.get("tab") || "Performance";
  const { id } = useParams(),
    navigate = useNavigate(),
    [selected, setSelected] = useState(sectionParams.get("version") || ""),
    [tab, setTab] = useState(
      [
        "Performance",
        "Tests",
        "Trades & proofs",
        "Guardrails",
        "Versions",
      ].includes(requestedTab)
        ? requestedTab
        : "Performance",
    );
  useEffect(() => {
    if (
      [
        "Performance",
        "Tests",
        "Trades & proofs",
        "Guardrails",
        "Versions",
      ].includes(requestedTab)
    )
      setTab(requestedTab);
  }, [requestedTab]);
  useEffect(() => {
    setSelected(sectionParams.get("version") || "");
  }, [sectionParams]);
  const suffix = selected ? "?version=" + selected : "",
    base = (publicView ? "/public/trading/strategies/" : "/strategies/") + id;
  const {
    data: s,
    error,
    reload,
    setError,
  } = useRemote<Strategy>(base + suffix);
  const trades = useRemote<{ items: Trade[]; total: number }>(
    base + "/trades" + suffix,
  );
  const [tests, setTests] = useState<Test[]>([]),
    [intents, setIntents] = useState<TradingIntent[]>([]),
    [busy, setBusy] = useState(false),
    [edit, setEdit] = useState<Version | null>(null),
    [dataset, setDataset] = useState("historical");
  async function extras() {
    if (!publicView) {
      setTests(
        (await api<{ items: Test[] }>("/strategies/" + id + "/tests" + suffix))
          .items,
      );
      setIntents(
        (
          await api<{ items: TradingIntent[] }>(
            "/strategies/" + id + "/intents",
          )
        ).items,
      );
    }
    await trades.reload();
  }
  useEffect(() => {
    void extras().catch((e) => setError(err(e)));
    const timer = setInterval(() => {
      if (!document.hidden) void extras().catch((e) => setError(err(e)));
    }, 10000);
    return () => clearInterval(timer);
  }, [id, selected, publicView]);
  async function act(path: string, body: unknown = {}, method = "POST") {
    setBusy(true);
    setError("");
    try {
      const r = await api<Record<string, unknown>>(
        "/strategies/" + id + path,
        post(body, method),
      );
      await reload();
      await extras();
      return r;
    } catch (e) {
      setError(err(e));
      return null;
    } finally {
      setBusy(false);
    }
  }
  async function adapt() {
    if (!s) return;
    if (
      ["LIVE", "DEGRADED"].includes(s.status) &&
      !(await act("/status", {
        status: "PAUSED",
        expected_version: s.current_version,
      }))
    )
      return;
    setEdit({ ...s, change_note: "" });
    setTab("Versions");
  }
  if (!s)
    return (
      <>
        <Heading title="Strategy" />
        <ErrorNotice error={error} />
        <p>Loading strategy…</p>
      </>
    );
  const p = s.performance,
    dep = p.deployment,
    current = s.version === s.current_version && !publicView;
  return (
    <>
      <Link className="back-link" to={publicView ? "/explore" : "/strategies"}>
        ← {publicView ? "Exchange" : "Strategies"}
      </Link>
      <Heading
        title={publicView ? s.agent_name : s.name}
        eyebrow={
          (publicView ? s.name : s.agent_name) + " / STRATEGY v" + s.version
        }
        text={
          s.description || "Test → Prove → Deploy → Monitor → Detect → Adapt"
        }
      >
        <div className="button-row">
          <Status value={dep?.step === 96 ? "COMPLETED" : s.status} />
          {!publicView && (
            <button
              className="primary"
              onClick={() => setShowPublication(true)}
            >
              {s.listed ? "Manage publication" : "Publish agent"}
            </button>
          )}
          <label className="inline-label">
            Version
            <select
              aria-label="Strategy version"
              value={selected || s.current_version}
              onChange={(e) => setSelected(e.target.value)}
            >
              {s.versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}
                  {v.version === s.current_version ? " · current" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Heading>
      <PaperNote />
      <ErrorNotice error={error} />
      {showPublication && !publicView && (
        <section
          className="panel editor publication-review"
          role="dialog"
          aria-label="Agent publication"
        >
          <h2>
            {s.listed
              ? "Manage public agent"
              : "Publish to the agent marketplace"}
          </h2>
          <p>
            Your recipe, agent identity, versions, tests, measured performance,
            trades and proofs become public. Visitors can create their own
            private agent from the recipe; they cannot control your agent or
            copy its capital or keys.
          </p>
          <HelpLink topic="publication" />
          <div className="button-row">
            <button
              className="primary"
              disabled={busy}
              onClick={async () => {
                if (await act("/publication", { listed: !s.listed }, "PUT"))
                  setShowPublication(false);
              }}
            >
              {s.listed ? "Remove public listing" : "Confirm publication"}
            </button>
            <button
              className="secondary"
              onClick={() => setShowPublication(false)}
            >
              Cancel
            </button>
          </div>
        </section>
      )}
      <DataSource
        source={p.market_data}
        label="Pre-deployment strategy test"
        exportUrl={
          "/v1" + base + "/market-data?kind=backtest&version=" + s.version
        }
      />
      <DataSource
        source={p.replay_market_data}
        label={
          publicView
            ? "Published agent replay period"
            : "Your agent's reserved replay period"
        }
        exportUrl={
          "/v1" + base + "/market-data?kind=replay&version=" + s.version
        }
      />
      {!publicView && dep && (
        <div className="replay-explanation">
          <strong>
            {dep.step === 0
              ? "Your agent has not executed yet."
              : dep.step >= 96
                ? "Historical replay completed."
                : "Historical replay in progress."}
          </strong>
          <p>
            {dep.step}/96 recorded candles processed · {p.verified_trades}{" "}
            verified paper fills. The backtest was calculated before this agent
            was created; it is not this agent's earned return.
          </p>
          <HelpLink topic="performance">
            Why a new agent already has backtest data
          </HelpLink>
        </div>
      )}
      {!publicView && s.onboarding_plan_id && (
        <div className="builder-boundary">
          <ShieldCheck size={20} />
          <div>
            <strong>Created from a reviewed intent</strong>
            <p>
              This paper agent uses a separate recorded market period. Advance
              the replay below to simulate actions and collect proofs.
            </p>
            <Link to={"/agents/new?plan=" + s.onboarding_plan_id}>
              View original intent & deployment review →
            </Link>
          </div>
        </div>
      )}
      {current && (
        <section className="lifecycle-actions panel">
          <label>
            Test dataset
            <select
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
            >
              <option value="historical">Recent exchange history</option>
            </select>
          </label>
          <button
            className="secondary"
            disabled={busy || s.status === "ARCHIVED"}
            onClick={() => void act("/tests", { dataset })}
          >
            <FlaskConical size={16} /> Run backtest
          </button>
          {!dep ? (
            <button
              className="primary"
              disabled={busy || s.status !== "VALIDATED"}
              onClick={() =>
                void act("/deploy", { expected_version: s.current_version })
              }
            >
              <Play size={16} /> Deploy paper
            </button>
          ) : (
            <>
              <button
                className="primary"
                disabled={
                  busy ||
                  !["LIVE", "DEGRADED"].includes(s.status) ||
                  dep.step >= 96
                }
                onClick={() =>
                  void act("/advance", { expected_step: dep.step, steps: 24 })
                }
              >
                <Play size={16} /> Replay next {Math.min(24, 96 - dep.step)}{" "}
                candles
              </button>
              <button
                className="secondary"
                disabled={busy || s.status === "ARCHIVED" || dep.step >= 96}
                onClick={() =>
                  void act("/status", {
                    status: ["LIVE", "DEGRADED"].includes(s.status)
                      ? "PAUSED"
                      : "LIVE",
                    expected_version: s.current_version,
                  })
                }
              >
                <Pause size={16} />
                {["LIVE", "DEGRADED"].includes(s.status) ? "Pause" : "Resume"}
              </button>
            </>
          )}
          <button
            className="secondary"
            disabled={busy || s.status === "ARCHIVED"}
            onClick={() => void adapt()}
          >
            <GitBranch size={16} />
            {["LIVE", "DEGRADED"].includes(s.status)
              ? "Pause & adapt"
              : "Create version"}
          </button>
          <small>
            {dep
              ? "Replay " + dep.step + "/96 candles · " + s.timeframe + " each"
              : "Test before deployment"}
          </small>
        </section>
      )}
      {dep && (
        <div className="replay-explanation">
          Each candle represents{" "}
          {s.timeframe === "1h"
            ? "1 hour"
            : s.timeframe === "4h"
              ? "4 hours"
              : "1 day"}
          . The next 24 candles cover{" "}
          {s.timeframe === "1h"
            ? "24 hours"
            : s.timeframe === "4h"
              ? "4 days"
              : "24 days"}{" "}
          of recorded history. This simulates decisions with your limits and
          stops for approval when required.{" "}
          <HelpLink topic="replay">What happens when I replay?</HelpLink>
        </div>
      )}
      {publicView && (
        <div className="button-row">
          <Link
            className="primary"
            to={"/agents/new?source=" + id + "&version=" + s.version}
          >
            Test this agent with my limits →
          </Link>
          <Link className="secondary" to={"/compare?ids=" + id}>
            Compare risk & performance
          </Link>
        </div>
      )}
      {!publicView && intents.some((i) => i.status === "AWAITING_APPROVAL") && (
        <div className="approval-banner">
          <b>Trading action needs your approval</b>
          <span>Replay is waiting for your decision.</span>
          <Link
            className="primary"
            to={
              "/trading/intents/" +
              intents.find((i) => i.status === "AWAITING_APPROVAL")!.intent_id
            }
          >
            Review & approve trade
          </Link>
        </div>
      )}
      <div className="metrics-v3">
        <Metric
          label="Paper replay return"
          value={pct(p.live_return)}
          className={tone(p.live_return)}
          note={
            p.verified_trades
              ? money(p.live.pnl) + " PnL"
              : "No executed paper trades yet"
          }
        />
        <Metric
          label="Backtest return"
          value={pct(p.backtest_return)}
          note="Pinned deployment baseline"
        />
        <Metric
          label="Backtest → paper gap"
          value={
            p.performance_gap == null ? "—" : num(p.performance_gap) + " pp"
          }
          className={tone(p.performance_gap)}
        />
        <Metric
          label="Max drawdown"
          value={p.verified_trades ? num(p.live.max_drawdown) + "%" : "—"}
          note={"Guardrail " + s.guardrails.max_drawdown + "%"}
        />
      </div>
      <div className="tabs v3-tabs">
        {["Performance", "Tests", "Trades & proofs", "Guardrails", "Versions"]
          .filter((t) => !publicView || t !== "Tests")
          .map((t) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
      </div>
      {tab === "Performance" && (
        <>
          <div className="lifecycle-grid">
            <section className="panel chart-panel">
              <h2>Performance, backed by fills</h2>
              <CurveChart
                live={p.live.equity_curve}
                backtest={p.backtest?.equity_curve}
                capital={s.starting_capital}
              />
              <p className="muted">{p.comparison_note}</p>
            </section>
            <HealthPanel health={s.health} />
          </div>
          <div className="metrics-v3 compact">
            <Metric
              label="Win rate"
              value={
                p.live.win_rate == null ? "—" : num(p.live.win_rate, 1) + "%"
              }
              note={p.live.closed_trade_count + " closed trades"}
            />
            <Metric
              label="Average win / loss"
              value={
                money(p.live.average_win) + " / " + money(p.live.average_loss)
              }
            />
            <Metric
              label="Profit factor"
              value={num(p.live.profit_factor)}
              note={p.live.profit_factor_note || "Gross wins / absolute losses"}
            />
            <Metric
              label="Fees / slippage"
              value={money(p.live.fees) + " / " + money(p.live.slippage)}
            />
          </div>
          <section className="panel editor">
            <div className="section-heading">
              <h2>Market regime</h2>
              <Status value={p.regime.status} />
            </div>
            <p>{p.regime.message}</p>
            {p.regime.current && (
              <div className="gap-row">
                <Metric
                  label="Recorded price"
                  value={money(p.regime.current.price)}
                />
                <Metric
                  label="Volatility / bar"
                  value={num(p.regime.current.volatility) + "%"}
                />
                <Metric label="Volume" value={money(p.regime.current.volume)} />
                <Metric label="Trend" value={p.regime.current.trend} />
              </div>
            )}
            <p className="muted">
              {p.regime.note ||
                "Run a test and advance the deployment to compare contexts."}
            </p>
          </section>
        </>
      )}
      {tab === "Tests" && (
        <section className="panel editor">
          <h2>Reproducible test runs</h2>
          <HelpLink topic="backtests" />
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Dataset / period</th>
                  <th>Version</th>
                  <th>Return</th>
                  <th>Drawdown</th>
                  <th>Win rate</th>
                  <th>Trades</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {tests.map((t) => (
                  <tr key={t.test_id}>
                    <td>
                      {t.dataset}
                      <small>
                        {when(t.market_period_start)} –{" "}
                        {when(t.market_period_end)}
                      </small>
                    </td>
                    <td>v{t.strategy_version}</td>
                    <td>{pct(t.metrics.return_pct)}</td>
                    <td>{num(t.metrics.max_drawdown)}%</td>
                    <td>
                      {t.metrics.win_rate == null
                        ? "—"
                        : num(t.metrics.win_rate) + "%"}
                    </td>
                    <td>{t.metrics.trade_count}</td>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => download(t, t.test_id + ".json")}
                      >
                        Export result
                      </button>
                      {t.test_id === p.baseline_test_id && (
                        <small>Deployment baseline</small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!tests.length && <p>Run a test to establish a baseline.</p>}
          <p className="muted">
            The baseline is pinned at deployment. Later tests never rewrite this
            comparison.
          </p>
        </section>
      )}
      {tab === "Trades & proofs" && (
        <>
          <section className="panel">
            <div className="panel-heading">
              <h2>{p.verified_trades} verified paper fills</h2>
            </div>
            <TradeTable
              items={trades.data?.items || []}
              publicView={publicView}
            />
            <ErrorNotice error={trades.error} />
          </section>
          {!publicView && (
            <section className="panel editor">
              <h2>Agent decisions & guardrail outcomes</h2>
              {intents.map((i) => (
                <Link
                  className="intent-link"
                  to={"/trading/intents/" + i.intent_id}
                  key={i.intent_id}
                >
                  <div>
                    <b>
                      {String(i.request.params.side)} ·{" "}
                      {String(i.request.params.quantity)}
                    </b>
                    <small>{i.reason.replaceAll("_", " ")}</small>
                  </div>
                  <Status value={i.status} />
                  <span>Inspect decision →</span>
                </Link>
              ))}
              {!intents.length && <p>No trading intents yet.</p>}
            </section>
          )}
        </>
      )}
      {tab === "Guardrails" && (
        <section className="panel editor">
          <h2>Rules for strategy v{s.version}</h2>
          <p>Immutable for this version. Risk checks run before every fill.</p>
          <div className="risk-grid">
            {Object.entries(s.guardrails).map(([k, v]) => (
              <div key={k}>
                <span>{k.replaceAll("_", " ")}</span>
                <strong>{Array.isArray(v) ? v.join(", ") : String(v)}</strong>
              </div>
            ))}
          </div>
          {current && dep && (
            <button
              className="secondary"
              disabled={
                busy ||
                !["LIVE", "DEGRADED"].includes(s.status) ||
                dep.step >= 96
              }
              onClick={async () => {
                const r = await act("/probe");
                if (r) navigate("/trading/intents/" + r.intent_id);
              }}
            >
              Check oversized order rejection
            </button>
          )}
          <p className="muted">
            This test order uses the same signed-intent and guardrail path. It
            is expected to be rejected.
          </p>
          <Link to="/infrastructure">
            Execution resources, approvals & integrations →
          </Link>
        </section>
      )}
      {tab === "Versions" && (
        <>
          <section className="panel editor">
            <h2>Version history</h2>
            {s.versions.map((v) => (
              <button
                className="version-history"
                key={v.version}
                onClick={() => setSelected(String(v.version))}
              >
                <b>v{v.version}</b>
                <span>
                  {v.change_note}
                  <small>{when(v.created_at)}</small>
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
          </section>
          {edit && (
            <form
              className="panel editor strategy-editor"
              onSubmit={async (e) => {
                e.preventDefault();
                const fields = Object.fromEntries(
                  Object.keys(defaults()).map((k) => [
                    k,
                    edit[k as keyof Version],
                  ]),
                );
                const result = await act("/versions", {
                  ...fields,
                  expected_version: s.current_version,
                });
                if (result) {
                  setEdit(null);
                  setSelected("");
                  await reload();
                }
              }}
            >
              <h2>Adapt as version {s.current_version + 1}</h2>
              <p>
                Past evidence stays on its original version. The new version
                starts with a fresh virtual portfolio after testing and
                deployment.
              </p>
              <VersionFields value={edit} setValue={setEdit} />
              <button disabled={busy} className="primary">
                Save new version
              </button>
            </form>
          )}
        </>
      )}
      {!publicView && (
        <section className="panel editor publication-panel">
          <div>
            <h2>Strategy marketplace publication</h2>
            <p>
              Publishing exposes this strategy, its agent identity, versions,
              performance, trades and full proofs. Original action histories
              keep their own privacy settings.
            </p>
          </div>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => {
              setShowPublication(true);
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          >
            Review publication settings
          </button>
          {s.listed && (
            <Link to={"/exchange/strategies/" + id}>
              View public strategy →
            </Link>
          )}
          {current && s.status !== "ARCHIVED" && (
            <button
              className="text-button"
              disabled={busy}
              onClick={() =>
                void act("/status", {
                  status: "ARCHIVED",
                  expected_version: s.current_version,
                })
              }
            >
              Archive strategy
            </button>
          )}
        </section>
      )}
    </>
  );
}
export function DegradationPage() {
  const { data, error, reload, setError } = useRemote<{ items: Alert[] }>(
    "/degradation/alerts",
  );
  return (
    <>
      <Heading
        title="Degradation alerts"
        text="Explainable thresholds, version-bound observations and owner actions."
      />
      <ErrorNotice error={error} />
      <section className="panel alerts-preview">
        {data?.items.map((a) => (
          <div className="alert-row" key={a.alert_id}>
            <Status value={a.severity} />
            <div>
              <Link to={"/strategies/" + a.strategy_id}>
                <b>
                  {a.strategy_name} · v{a.version}
                </b>
              </Link>
              <p>{a.message}</p>
              <small>
                {when(a.created_at)} · {a.kind.replaceAll("_", " ")}
              </small>
            </div>
            <button
              className="secondary"
              disabled={!!a.acknowledged}
              onClick={async () => {
                try {
                  await api(
                    "/degradation/alerts/" + a.alert_id + "/acknowledge",
                    post(),
                  );
                  await reload();
                } catch (e) {
                  setError(err(e));
                }
              }}
            >
              {a.acknowledged ? "Acknowledged" : "Acknowledge"}
            </button>
          </div>
        ))}
        {data && !data.items.length && <p className="empty">No alerts yet.</p>}
      </section>
    </>
  );
}

export function TradingIntentPage() {
  const { id } = useParams(),
    {
      data: i,
      error,
      reload,
      setError,
    } = useRemote<TradingIntent>("/trading/intents/" + id);
  const [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  async function decide(decision: string) {
    if (!i) return;
    setBusy(true);
    try {
      await api(
        "/trading/intents/" + id + "/decision",
        post({
          decision,
          intent_hash: i.intent_hash,
          policy_version: i.policy_version,
          note,
        }),
      );
      await reload();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading title="Trading intent & decision" />
      <ErrorNotice error={error} />
      {i && (
        <>
          <Link to={"/strategies/" + i.strategy_id}>← Strategy</Link>
          <PaperNote />
          <div className="lifecycle-grid">
            <section className="panel editor">
              <Status value={i.status} />
              <h2>What did the agent request?</h2>
              <p>{i.request.reason}</p>
              <Json value={i.request.params} />
              <h2>Was it allowed?</h2>
              <p>{i.reason.replaceAll("_", " ")}</p>
              <details>
                <summary>Policy & decision context</summary>
                <Json value={{ policy: i.policy, decision: i.decision }} />
              </details>
              {i.receipt ? (
                <Link
                  className="primary"
                  to={"/trades/" + i.receipt.trade_id + "/proof"}
                >
                  Open Trading Proof →
                </Link>
              ) : (
                <p>
                  {i.status === "REJECTED"
                    ? "No fill was executed. The rejection is recorded in the signed agent audit trail."
                    : "No fill has executed yet."}
                </p>
              )}
            </section>
            {i.status === "AWAITING_APPROVAL" && (
              <section className="panel editor approval-box">
                <h2>Human decision required</h2>
                <p>
                  Approval binds this exact intent hash and strategy version.
                </p>
                <code>{i.intent_hash}</code>
                <p>Expires: {when(i.approval_expires_at)}</p>
                <label>
                  Decision note
                  <input
                    value={note}
                    maxLength={500}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
                <div className="button-row">
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => void decide("approve")}
                  >
                    Approve this trade
                  </button>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => void decide("deny")}
                  >
                    Deny trade
                  </button>
                </div>
              </section>
            )}
          </div>
        </>
      )}
    </>
  );
}
type Proof = {
  receipt: Record<string, unknown> & {
    receipt_hash: string;
    signature: string;
    public_key: string;
    trade: Trade;
    sequence: number;
    strategy_version: number;
    decision_source: string;
    execution: Record<string, unknown>;
  };
  chain: Record<string, unknown>[];
  checks: {
    valid: boolean;
    signature_valid: boolean;
    chain_valid: boolean;
    readback_matches: boolean;
    mode: string;
    on_chain: boolean;
  };
};
export function TradingProofPage({
  publicView = false,
}: {
  publicView?: boolean;
}) {
  const { id } = useParams(),
    {
      data: p,
      error,
      reload,
      setError,
    } = useRemote<Proof>(
      (publicView ? "/public/trading/trades/" : "/trades/") + id + "/proof",
    );
  const [trusted, setTrusted] = useState(""),
    [local, setLocal] = useState<boolean | null>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    void api<{ poa_public_key: string }>("/config")
      .then((c) => setTrusted(c.poa_public_key))
      .catch((e) => setError(err(e)));
  }, []);
  async function verify() {
    setBusy(true);
    try {
      const fresh = await reload();
      if (!fresh) return;
      let valid = true;
      const decode = (s: string) =>
        Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
      const key = await crypto.subtle.importKey(
        "raw",
        decode(trusted),
        "Ed25519",
        false,
        ["verify"],
      );
      let previous: unknown = null;
      for (const [index, item] of fresh.chain.entries()) {
        const { receipt_hash, signature, ...body } = item;
        const bytes = await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(canonicalize(body)!),
        );
        const hex = [...new Uint8Array(bytes)]
          .map((x) => x.toString(16).padStart(2, "0"))
          .join("");
        valid =
          valid &&
          hex === receipt_hash &&
          body.public_key === trusted &&
          body.sequence === index + 1 &&
          body.previous_receipt_hash === previous &&
          (await crypto.subtle.verify(
            "Ed25519",
            key,
            decode(String(signature)),
            bytes,
          ));
        previous = receipt_hash;
      }
      setLocal(valid);
    } catch (e) {
      setLocal(false);
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Trading Proof"
        text="Strategy → decision → intent → fill → verified ledger outcome."
      />
      <PaperNote />
      <ErrorNotice error={error} />
      {p && (
        <>
          <div className="metrics-v3">
            <Metric
              label="Strategy version"
              value={"v" + p.receipt.strategy_version}
            />
            <Metric
              label="Trade"
              value={
                p.receipt.trade.side + " " + num(p.receipt.trade.quantity, 6)
              }
            />
            <Metric
              label="Executed price"
              value={money(p.receipt.trade.executed_price)}
            />
            <Metric label="Proof sequence" value={"#" + p.receipt.sequence} />
          </div>
          <div className="lifecycle-grid">
            <section className="panel editor">
              <h2>Execution evidence</h2>
              <p>
                <b>Paper ledger</b> · on-chain execution: <b>No</b>
              </p>
              <p>
                Decision source:{" "}
                {p.receipt.decision_source.replaceAll("_", " ")}. Hosted paper
                decisions use a separately delegated runner key.
              </p>
              <p>
                This signed record proves the simulation recorded by Tracy. It
                is not a Jupiter fill or blockchain transaction.
              </p>
              <Json value={p.receipt.execution} />
              <Link
                to={
                  (publicView ? "/exchange/strategies/" : "/strategies/") +
                  String(p.receipt.strategy_id)
                }
              >
                Open strategy →
              </Link>
            </section>
            <section className="panel editor">
              <h2>Verify evidence</h2>
              <label>
                Trusted Tracy public key
                <input
                  value={trusted}
                  onChange={(e) => {
                    setTrusted(e.target.value);
                    setLocal(null);
                  }}
                />
              </label>
              <p className="muted">
                Defaults to this server's published key. Pin a separately
                obtained key to verify its identity.
              </p>
              <button
                className="primary"
                disabled={busy || !trusted}
                onClick={() => void verify()}
              >
                {busy ? "Checking…" : "Verify proof now"}
              </button>
              <Json
                value={{ ...p.checks, browser_hash_signature_chain: local }}
              />
              <button
                className="secondary"
                onClick={() => download(p, "trading-proof-" + id + ".json")}
              >
                Download proof & chain
              </button>
            </section>
          </div>
          <details className="panel editor">
            <summary>Full signed TradingReceipt</summary>
            <Json value={p.receipt} />
          </details>
        </>
      )}
    </>
  );
}
export function InfrastructurePage() {
  const links = [
    [
      "/control",
      "Agent control center",
      "Register identities, grant tasks and inspect generic intents.",
    ],
    [
      "/control/approvals",
      "Human approvals",
      "Review sensitive non-trading actions.",
    ],
    [
      "/control/resources",
      "Execution resources",
      "Controlled signers, databases and API bindings.",
    ],
    [
      "/control/integrations",
      "Integrations",
      "Python SDK, MCP and LangChain tools.",
    ],
    [
      "/installed",
      "Installed agents",
      "Existing hosted Devnet payout recipes.",
    ],
    ["/payouts", "Payout overview", "Native SOL history and verification."],
    ["/demo", "Run an action", "Devnet transfer workflow."],
    ["/connect", "Connect SDK", "Original payout integration."],
    ["/activity", "Action history", "Search original signed actions."],
    ["/analytics", "Action analytics", "Original execution metrics."],
    ["/funding", "Devnet funding", "Test wallet balances."],
    ["/watchlist", "Watchlist", "Saved agent profiles."],
    ["/notifications", "Account notifications", "Account and platform events."],
    [
      "/legacy/explore",
      "Legacy marketplace",
      "Preserved payout marketplace and comparisons.",
    ],
  ];
  return (
    <>
      <Heading
        title="Guardrails & infrastructure"
        text="Trading limits live on each strategy version. The original control layer remains available here."
      />
      <div className="strategy-grid">
        {links.map(([to, title, text]) => (
          <Link className="strategy-card" to={to} key={to}>
            <ShieldCheck size={20} />
            <h2>{title}</h2>
            <p>{text}</p>
            <span className="proof-link">Open →</span>
          </Link>
        ))}
      </div>
    </>
  );
}
export function StrategyTestsPage() {
  const { data, error } = useRemote<{ items: Strategy[] }>("/strategies");
  return (
    <>
      <Heading
        title="Strategy tests"
        text="Select a strategy to run reproducible tests, compare versions and export results."
      />
      <ErrorNotice error={error} />
      <div className="strategy-grid">
        {data?.items.map((s) => (
          <StrategyCard key={s.strategy_id} s={s} />
        ))}
      </div>
      {data && !data.items.length && (
        <Link className="primary" to="/strategies/new">
          Create a strategy first →
        </Link>
      )}
    </>
  );
}
export function TradingPublicAgent() {
  const { id } = useParams(),
    { data, error } = useRemote<{
      agent_id: string;
      name: string;
      description: string;
      strategies: Strategy[];
      legacy_listed: boolean;
    }>("/public/trading/agents/" + id);
  return (
    <>
      <Heading
        title={data?.name || "Agent profile"}
        eyebrow="PERFORMANCE / RISK / EVIDENCE"
        text={
          data?.description ||
          "Published strategy versions, recorded performance and evidence. Inspect a version before testing your personal instance."
        }
      />
      <PaperNote />
      <ErrorNotice error={error} />
      <div className="strategy-grid">
        {data?.strategies.map((s) => (
          <StrategyCard key={s.strategy_id} s={s} publicView />
        ))}
      </div>
      {data && !data.strategies.length && (
        <p>No published trading strategy yet.</p>
      )}
      {data?.legacy_listed && (
        <section className="panel editor">
          <h2>Additional action evidence</h2>
          <Link to={"/legacy/agents/" + id}>
            Inspect the original action record →
          </Link>
        </section>
      )}
    </>
  );
}
export function TradingCompare() {
  const [params, setParams] = useSearchParams(),
    all = useRemote<{ items: Strategy[] }>("/public/trading/strategies");
  const selected = (params.get("ids") || "").split(",").filter(Boolean),
    chosen = (all.data?.items || []).filter((s) =>
      selected.includes(s.strategy_id),
    );
  const rows: [string, (s: Strategy) => string][] = [
    ["Evidence mode", () => "Historical paper replay"],
    ["Strategy version", (s) => "v" + s.version],
    ["Market / interval", (s) => s.market + " / " + s.timeframe],
    ["Starting capital", (s) => money(s.starting_capital)],
    [
      "Fee / slippage (bps)",
      (s) => s.strategy_config.fee_bps + " / " + s.strategy_config.slippage_bps,
    ],
    [
      "Max position / trade",
      (s) =>
        money(s.guardrails.max_position_size) +
        " / " +
        money(s.guardrails.max_trade_size),
    ],
    [
      "Daily loss / drawdown limits",
      (s) =>
        s.guardrails.max_daily_loss + "% / " + s.guardrails.max_drawdown + "%",
    ],
    [
      "Paper return",
      (s) =>
        s.performance.verified_trades ? pct(s.performance.live_return) : "—",
    ],
    ["Max drawdown", (s) => num(s.performance.live.max_drawdown) + "%"],
    [
      "Win rate",
      (s) =>
        s.performance.live.win_rate == null
          ? "—"
          : num(s.performance.live.win_rate) + "%",
    ],
    [
      "Backtest/paper gap",
      (s) =>
        s.performance.performance_gap == null
          ? "—"
          : num(s.performance.performance_gap) + " pp",
    ],
    ["Health", (s) => (s.health.score ?? "—") + " / 100 · " + s.health.status],
    ["Verified trades", (s) => String(s.performance.verified_trades)],
    ["Closed trades", (s) => String(s.performance.live.closed_trade_count)],
    ["Fees", (s) => money(s.performance.live.fees)],
    ["Slippage", (s) => money(s.performance.live.slippage)],
    [
      "Replay period",
      (s) =>
        s.performance.track_record_start
          ? new Date(
              s.performance.track_record_start * 1000,
            ).toLocaleDateString() +
            " – " +
            new Date(
              s.performance.track_record_end! * 1000,
            ).toLocaleDateString()
          : "No data",
    ],
  ];
  return (
    <>
      <Heading
        title="Compare agents"
        text="Compare performance with risk, sample size and evidence. Returns alone are not a ranking."
      />
      <PaperNote />
      <ErrorNotice error={all.error} />
      <section className="panel editor">
        <h2>Choose 2–4 agent strategies</h2>
        {all.data && !all.data.items.length && (
          <p>
            No agents have been published yet.{" "}
            <Link to="/">Open marketplace →</Link>
          </p>
        )}
        <div className="comparison-select">
          {all.data?.items.map((s) => (
            <label key={s.strategy_id}>
              <input
                type="checkbox"
                checked={selected.includes(s.strategy_id)}
                disabled={
                  selected.length >= 4 && !selected.includes(s.strategy_id)
                }
                onChange={(e) =>
                  setParams({
                    ids: (e.target.checked
                      ? [...selected, s.strategy_id]
                      : selected.filter((x) => x !== s.strategy_id)
                    ).join(","),
                  })
                }
              />
              {s.agent_name} / {s.name} v{s.version}
            </label>
          ))}
        </div>
      </section>
      {chosen.length >= 2 ? (
        <section className="panel table-scroll">
          <table className="compare-table">
            <thead>
              <tr>
                <th>Metric</th>
                {chosen.map((s) => (
                  <th key={s.strategy_id}>
                    <Link to={"/exchange/strategies/" + s.strategy_id}>
                      {s.agent_name} / {s.name}
                    </Link>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(([name, fn]) => (
                <tr key={name}>
                  <th>{name}</th>
                  {chosen.map((s) => (
                    <td key={s.strategy_id}>{fn(s)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        <p className="empty">
          Select at least two published agent strategies to compare.
        </p>
      )}
      <p className="muted">
        Check the replay periods and capital settings. These are cumulative,
        unannualized returns over historical market periods.{" "}
        <Link to="/leaderboard">Rank agents under matching conditions →</Link>
      </p>
    </>
  );
}

export function TradingProofIndex() {
  const strategies = useRemote<{ items: Strategy[] }>("/strategies"),
    [selected, setSelected] = useState(""),
    [trades, setTrades] = useState<Trade[]>([]),
    [error, setError] = useState("");
  const id = selected || strategies.data?.items[0]?.strategy_id;
  useEffect(() => {
    if (id)
      void api<{ items: Trade[] }>("/strategies/" + id + "/trades")
        .then((r) => setTrades(r.items))
        .catch((e) => setError(err(e)));
  }, [id]);
  return (
    <>
      <Heading
        title="Trading proofs"
        text="Inspect individual fills, verify signed chains and read the execution ledger."
      />
      <PaperNote />
      <ErrorNotice error={error || strategies.error} />
      <div className="toolbar">
        <label>
          Strategy
          <select
            value={id || ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {strategies.data?.items.map((s) => (
              <option value={s.strategy_id} key={s.strategy_id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <Link className="secondary" to="/verify">
          Verify original action receipt
        </Link>
      </div>
      <section className="panel">
        <TradeTable items={trades} />
      </section>
    </>
  );
}

export function TradingMethodology() {
  return (
    <>
      <Heading
        title="How Tracy measures a strategy"
        eyebrow="METHODOLOGY / V3"
        text="Every number has a source, a version and a defined calculation."
      />
      <PaperNote />
      <div className="lifecycle-grid">
        <section className="panel editor">
          <h2>Performance accounting</h2>
          <p>
            PnL = marked portfolio equity − starting capital. Return = PnL /
            starting capital × 100. Open positions are marked at the current
            recorded market quote; realized PnL uses average cost, including
            entry fees.
          </p>
          <p>
            Win rate counts profitable sell executions among all closed sell
            executions. A partial exit counts as a closed observation. Max
            drawdown is the largest percentage decline from an equity high-water
            mark, including the initial capital.
          </p>
          <p>
            Profit factor = gross winning realized PnL / absolute gross losing
            realized PnL. With no losing exits it is unavailable, rather than an
            invented finite score. Fees and price slippage are shown separately;
            both affect PnL.
          </p>
          <p>
            Backtest/paper gap = cumulative paper replay return − pinned
            backtest return, in percentage points. Different recorded market
            periods and sample sizes are disclosed; this is not an annualized or
            risk-adjusted ranking.
          </p>
        </section>
        <section className="panel editor">
          <h2>Strategy Health</h2>
          <HelpLink topic="health" />
          <p>
            30% paper performance + 25% drawdown + 20% backtest/paper gap + 15%
            execution fidelity + 10% recent consistency.
          </p>
          <p>
            Each strategy exposes the exact normalized component formulas under
            “Why this score?”. Five closed trades and a baseline test are
            required before a score appears.
          </p>
          <p>
            Rules monitor loss of return, drawdown, widening gap, falling recent
            win rate and excess slippage. Critical drawdown pauses the paper
            deployment. Alerts describe observed behavior; they do not predict
            market outcomes.
          </p>
        </section>
      </div>
      <section className="panel editor">
        <h2>Evidence and limits</h2>
        <p>
          Only fills with valid matching Trading Proofs contribute to
          performance. Paper fills, strategy versions and proof records are
          append-only. Editing a strategy creates a new version and a separate
          virtual portfolio.
        </p>
        <p>
          TradingReceipt binds the version, signed intent, guardrail decision,
          optional approval, exact fill, market context and marked outcome. A
          hash chain and Ed25519 signature make modifications detectable against
          a pinned trusted Tracy key.
        </p>
        <p>
          The current trading adapter is a deterministic paper ledger. No
          Jupiter swap or on-chain trading fill is claimed. The existing native
          SOL Devnet gateway and original receipts remain separate, available
          infrastructure.
        </p>
        <p>
          The operator and signing key are trusted. To detect a truncated
          history, retain an independent latest hash/sequence checkpoint. A
          signed paper record does not establish profitable real-world
          performance.
        </p>
        <Link to="/legacy/methodology">
          Read the original action verification methodology →
        </Link>
      </section>
    </>
  );
}
