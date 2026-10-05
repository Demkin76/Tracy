import React, { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCheck,
  FlaskConical,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api } from "./api";
import { useApp } from "./app-context";
import { ErrorNotice, err } from "./PublicPages";
import "./agent-builder.css";
import { agentDefaults as defaults, type Configuration } from "./agent-config";
import { HelpLink, ProposalView, type CopilotResult } from "./Copilot";

type MarketSource = {
  provider: string;
  market: string;
  period_start: number;
  period_end: number;
  fetched_at: number;
  snapshot_id: string;
};
type Plan = {
  plan_id: string;
  review_hash: string;
  configuration: Configuration;
  strategy_id: string | null;
  report: {
    market_data?: MarketSource;
    replay_market_data?: MarketSource;
    ready: boolean;
    passed: number;
    total: number;
    note: string;
    checks: {
      skipped?: boolean;
      expected?: string[];
      input?: unknown;
      observed?: unknown;
      name: string;
      passed: boolean;
      decision: string;
      reason: string;
    }[];
    simulations: {
      dataset: string;
      market_data?: MarketSource;
      metrics: {
        return_pct: number;
        max_drawdown: number;
        trade_count: number;
      };
    }[];
  };
};
const runners: Record<string, string> = {
  mean_reversion: "Mean reversion",
  momentum: "Momentum",
  buy_hold: "Buy & hold",
};
const money = (n: number) =>
  n.toLocaleString("en-US", { maximumFractionDigits: 2 }) + " USDC";
const post = (value: unknown) => ({
  method: "POST",
  body: JSON.stringify(value),
});
const steps = ["Describe", "Guardrails", "Test", "Review"];

export function AgentBuilder() {
  const { user, refresh } = useApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const storageKey = "tracy-agent-draft:" + user.user_id;
  const [value, setValue] = useState<Configuration>(() => {
    try {
      const saved = sessionStorage.getItem(storageKey);
      return saved ? JSON.parse(saved) : defaults();
    } catch {
      return defaults();
    }
  });
  const [step, setStep] = useState(0);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [suggested, setSuggested] = useState(false);
  const planId = params.get("plan"),
    source = params.get("source");
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      /* Draft remains usable without storage. */
    }
  }, [value, storageKey]);
  useEffect(() => {
    if (!planId || plan?.plan_id === planId) return;
    let active = true;
    setBusy(true);
    api<Plan>("/agent-plans/" + planId)
      .then((p) => {
        if (active) {
          setPlan(p);
          setValue(p.configuration);
          setStep(2);
        }
      })
      .catch((e) => {
        if (active) setError(err(e));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [planId]);
  useEffect(() => {
    if (!source || planId) return;
    let active = true;
    setBusy(true);
    api<Configuration & { version: number }>(
      "/public/trading/strategies/" +
        source +
        (params.get("version") ? "?version=" + params.get("version") : ""),
    )
      .then((s) => {
        if (active)
          setValue({
            ...defaults(),
            name: s.name.slice(0, 90) + " copy",
            source_strategy_id: source,
            source_version: s.version,
            goal: "Evaluate " + s.name + " in my own paper workspace.",
            market: s.market,
            symbols: s.symbols,
            timeframe: s.timeframe,
            starting_capital: s.starting_capital,
            strategy_config: s.strategy_config,
            guardrails: s.guardrails,
          });
      })
      .catch((e) => {
        if (active) setError(err(e));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [source]);

  function change(next: Configuration) {
    setValue(next);
    setPlan(null);
    setAcknowledged(false);
    setError("");
    if (planId) setParams({}, { replace: true });
  }
  const [extraction, setExtraction] = useState<CopilotResult | null>(null);
  const [useAI, setUseAI] = useState(false),
    [aiAvailable, setAiAvailable] = useState(false),
    [aiProvider, setAiProvider] = useState("AI provider");
  useEffect(() => {
    api<{ ai_available: boolean; provider: string | null }>("/copilot/status")
      .then((r) => {
        setAiAvailable(r.ai_available);
        setAiProvider(r.provider || "AI provider");
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!params.get("copilot")) return;
    const key = "tracy-copilot-pending:" + user.user_id;
    try {
      const pending = sessionStorage.getItem(key);
      if (pending) {
        setValue(JSON.parse(pending));
        setPlan(null);
        setAcknowledged(false);
        setStep(1);
        setSuggested(true);
        setExtraction(null);
        sessionStorage.removeItem(key);
      }
    } catch {
      setError("Could not restore Copilot draft. Please retry.");
    }
  }, [params.get("copilot")]);
  async function suggest(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<CopilotResult>(
        "/copilot/message",
        post({
          message: value.goal,
          page: "/agents/new",
          draft: value,
          purpose: "extract",
          use_ai: useAI,
        }),
      );
      setExtraction(result);
      if (result.proposal) {
        change(result.proposal.configuration);
        setSuggested(true);
        setStep(1);
      } else {
        setError(result.questions.join(" ") || result.answer);
      }
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  async function test() {
    setBusy(true);
    setError("");
    setAcknowledged(false);
    try {
      const p = await api<Plan>("/agent-plans", post(value));
      setPlan(p);
      setParams({ plan: p.plan_id }, { replace: true });
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  async function deploy() {
    if (!plan || !acknowledged) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ strategy_id: string }>(
        "/agent-plans/" + plan.plan_id + "/deploy",
        post({ reviewed_hash: plan.review_hash, acknowledged }),
      );
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        /* Optional storage. */
      }
      await refresh();
      navigate("/strategies/" + result.strategy_id + "?created=1");
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  function risk(key: keyof Configuration["guardrails"], n: number) {
    change({ ...value, guardrails: { ...value.guardrails, [key]: n } });
  }
  function runner(
    key: keyof Configuration["strategy_config"],
    n: number | string,
  ) {
    change({
      ...value,
      strategy_config: { ...value.strategy_config, [key]: n },
    });
  }
  const reviewed = plan?.configuration || value;
  const g = reviewed.guardrails;

  return (
    <div className="agent-builder">
      <div className="builder-heading">
        <div>
          <div className="eyebrow">INTENT FIRST · TRACY</div>
          <h1>Test an agent before it acts.</h1>
          <p>
            Review the strategy and your limits. Test, then approve a private
            paper instance. Publication is a separate step in Developer studio.
          </p>
        </div>
        <span className="builder-mode">
          <ShieldCheck size={14} /> Paper trading
        </span>
      </div>
      <ol className="builder-steps" aria-label="Agent setup progress">
        {steps.map((label, i) => (
          <li
            key={label}
            aria-current={i === step ? "step" : undefined}
            className={i === step ? "current" : i < step ? "done" : ""}
          >
            <span>{i < step ? <Check size={15} /> : "0" + (i + 1)}</span>
            {label}
          </li>
        ))}
      </ol>
      <ErrorNotice error={error} />
      <div className="builder-layout">
        <section className="panel builder-main" aria-busy={busy}>
          {step === 0 && (
            <form onSubmit={suggest}>
              <span className="builder-kicker">01 / THE JOB</span>
              <h2>What do you want this agent to do?</h2>
              <p>
                Start with the outcome you want and the risks you want to avoid.
              </p>
              <label className="intent-label">
                Your intent
                <textarea
                  required
                  minLength={10}
                  maxLength={1000}
                  rows={5}
                  value={value.goal}
                  disabled={busy}
                  onChange={(e) => change({ ...value, goal: e.target.value })}
                  placeholder="I want an agent that trades SOL/USDC using mean reversion, with small positions and my approval for larger trades."
                />
              </label>
              <div className="builder-examples">
                <span>Try a starting point</span>
                {[
                  [
                    "Cautious SOL trader",
                    "Trade SOL/USDC with mean reversion. Keep positions small and ask me before larger trades.",
                  ],
                  [
                    "Follow market momentum",
                    "Test a momentum strategy on ETH/USDC. Limit exposure and stop new buys when losses grow.",
                  ],
                ].map(([title, goal]) => (
                  <button
                    type="button"
                    className="secondary"
                    key={title}
                    onClick={() => {
                      change({ ...defaults(), goal });
                      setSuggested(false);
                    }}
                  >
                    {title}
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
              <p className="builder-note">
                Your text fills recognized fields. Unspecified values stay
                visible as defaults, and conflicts require clarification.
              </p>
              {aiAvailable && (
                <label className="builder-ai-choice">
                  <input
                    type="checkbox"
                    checked={useAI}
                    onChange={(e) => setUseAI(e.target.checked)}
                  />{" "}
                  Use AI to interpret my intent (sends this text and draft
                  settings to {aiProvider}; provider data terms apply)
                </label>
              )}
              <HelpLink topic="intent">How text becomes settings</HelpLink>
              <div className="builder-actions">
                <Link to="/agents">Cancel</Link>
                <button className="primary" disabled={busy}>
                  Suggest guardrails <ArrowRight size={16} />
                </button>
              </div>
            </form>
          )}
          {step === 1 && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setStep(2);
              }}
            >
              <span className="builder-kicker">02 / PERMISSION TO ACT</span>
              <h2>Decide what it can—and cannot—do.</h2>
              {value.source_strategy_id && (
                <p className="builder-note">
                  Private agent from{" "}
                  <Link
                    to={
                      "/exchange/strategies/" +
                      value.source_strategy_id +
                      "?version=" +
                      value.source_version
                    }
                  >
                    source strategy v{value.source_version}
                  </Link>
                  . This copy gets its own identity and empty execution history.
                </p>
              )}
              <p>
                These settings become the execution policy. You can edit every
                suggested limit.
              </p>
              {extraction && (
                <details className="intent-extraction" open>
                  <summary>What Tracy understood from your text</summary>
                  <ProposalView result={extraction} />
                  <p>
                    Other fields keep their existing/default values. Confirm or
                    edit them below.
                  </p>
                </details>
              )}
              <div className="builder-fields">
                <label>
                  Agent name
                  <input
                    required
                    maxLength={100}
                    value={value.name}
                    onChange={(e) => change({ ...value, name: e.target.value })}
                  />
                </label>
                <label>
                  Risk preference
                  <select
                    value={value.risk_tolerance}
                    onChange={(e) => {
                      const r = e.target
                        .value as Configuration["risk_tolerance"];
                      change({
                        ...value,
                        risk_tolerance: r,
                        guardrails: {
                          ...value.guardrails,
                          max_daily_loss: { low: 1, medium: 3, high: 5 }[r],
                          max_drawdown: { low: 10, medium: 15, high: 20 }[r],
                        },
                      });
                    }}
                  >
                    <option value="low">Low · cautious</option>
                    <option value="medium">Medium · balanced</option>
                    <option value="high">High · more exposure</option>
                  </select>
                </label>
                <label>
                  Allowed market
                  <select
                    value={value.market}
                    onChange={(e) => {
                      const market = e.target.value;
                      change({
                        ...value,
                        market,
                        symbols: market.split("/"),
                        guardrails: {
                          ...value.guardrails,
                          allowed_markets: [market],
                          allowed_tokens: market.split("/"),
                        },
                      });
                    }}
                  >
                    <option>SOL/USDC</option>
                    <option>ETH/USDC</option>
                    <option>BTC/USDC</option>
                  </select>
                </label>
                <label>
                  Strategy template
                  <select
                    value={value.strategy_config.runner}
                    onChange={(e) => runner("runner", e.target.value)}
                  >
                    {Object.entries(runners).map(([k, label]) => (
                      <option key={k} value={k}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <NumberField
                  label="Paper capital (USDC)"
                  value={value.starting_capital}
                  min={100}
                  max={10000000}
                  onChange={(n) => change({ ...value, starting_capital: n })}
                />
                <NumberField
                  label="Max position (USDC)"
                  value={value.guardrails.max_position_size}
                  min={0.01}
                  max={value.starting_capital}
                  onChange={(n) => risk("max_position_size", n)}
                />
                <NumberField
                  label="Max trade (USDC)"
                  value={value.guardrails.max_trade_size}
                  min={0.01}
                  max={value.guardrails.max_position_size}
                  onChange={(n) => risk("max_trade_size", n)}
                />
                <NumberField
                  label="Approval required above (USDC)"
                  value={value.guardrails.human_approval_above}
                  min={0}
                  max={100000000}
                  onChange={(n) => risk("human_approval_above", n)}
                />
                <NumberField
                  label="Daily loss threshold (%)"
                  value={value.guardrails.max_daily_loss}
                  min={0.01}
                  max={100}
                  onChange={(n) => risk("max_daily_loss", n)}
                />
                <NumberField
                  label="Drawdown threshold (%)"
                  value={value.guardrails.max_drawdown}
                  min={0.01}
                  max={100}
                  onChange={(n) => risk("max_drawdown", n)}
                />
                <NumberField
                  label="Capital per entry (%)"
                  value={value.strategy_config.allocation_pct}
                  min={0.01}
                  max={90}
                  onChange={(n) => runner("allocation_pct", n)}
                />
                <label>
                  Timeframe
                  <select
                    value={value.timeframe}
                    onChange={(e) =>
                      change({ ...value, timeframe: e.target.value })
                    }
                  >
                    <option value="1h">1 hour</option>
                    <option value="4h">4 hours</option>
                    <option value="1d">1 day</option>
                  </select>
                </label>
              </div>
              <div className="builder-boundary">
                <ShieldCheck size={20} />
                <div>
                  <strong>
                    Trading only. No leverage, withdrawals or short selling.
                  </strong>
                  <p>
                    Loss thresholds block new buys. They do not cap losses on
                    existing positions or guarantee a stop-loss execution.
                  </p>
                </div>
              </div>
              <details className="builder-advanced">
                <summary>Strategy & test details</summary>
                <div className="builder-fields">
                  <NumberField
                    label="Lookback (bars)"
                    value={value.strategy_config.lookback}
                    min={2}
                    max={20}
                    step={1}
                    onChange={(n) => runner("lookback", n)}
                  />
                  <NumberField
                    label="Exit after (bars)"
                    value={value.strategy_config.exit_after_bars}
                    min={1}
                    max={48}
                    step={1}
                    onChange={(n) => runner("exit_after_bars", n)}
                  />
                  <NumberField
                    label="Signal threshold (bps)"
                    value={value.strategy_config.threshold_bps}
                    min={0}
                    max={5000}
                    onChange={(n) => runner("threshold_bps", n)}
                  />
                  <NumberField
                    label="Fee assumption (bps)"
                    value={value.strategy_config.fee_bps}
                    min={0}
                    max={200}
                    onChange={(n) => runner("fee_bps", n)}
                  />
                  <NumberField
                    label="Slippage assumption (bps)"
                    value={value.strategy_config.slippage_bps}
                    min={0}
                    max={500}
                    onChange={(n) => runner("slippage_bps", n)}
                  />
                </div>
                <p>
                  Three recorded market periods · 96 closed candles each.
                  Approval requests are checked separately from strategy
                  returns.
                </p>
              </details>
              <div className="builder-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setStep(0)}
                >
                  <ArrowLeft size={15} /> Intent
                </button>
                <button className="primary" disabled={busy}>
                  Continue to test <ArrowRight size={15} />
                </button>
              </div>
            </form>
          )}
          {step === 2 && (
            <>
              <span className="builder-kicker">03 / BEFORE IT ACTS</span>
              <h2>Test the strategy. Challenge the limits.</h2>
              <p>
                Tracy fetches recorded exchange candles and stores a
                reproducible snapshot. No agent is created and no funds move.
              </p>
              {!plan ? (
                <div className="builder-test-empty">
                  <FlaskConical size={32} />
                  <h3>Try it before you create it.</h3>
                  <p>
                    Run executable boundary checks and replay the strategy
                    through three consecutive historical periods from Binance.
                    The latest 96 candles are reserved for paper replay.
                  </p>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => void test()}
                  >
                    {busy
                      ? "Fetching candles & testing…"
                      : "Run backtests & checks"}
                  </button>
                </div>
              ) : (
                <>
                  <div className="builder-test-score">
                    <CheckCheck size={25} />
                    <div>
                      <strong>
                        {plan.report.passed}/{plan.report.total} guardrail
                        checks passed
                      </strong>
                      <span>
                        {plan.report.ready
                          ? "Ready for your review"
                          : "Resolve failed checks before deployment"}
                      </span>
                    </div>
                  </div>
                  <ul className="builder-checks">
                    {plan.report.checks.map((c) => (
                      <li key={c.name}>
                        <span
                          className={c.passed ? "check-pass" : "check-fail"}
                        >
                          {c.skipped ? "—" : c.passed ? "✓" : "!"}
                        </span>
                        <span>
                          {c.name}
                          <small>{c.reason.replaceAll("_", " ")}</small>
                          {c.input != null && (
                            <details className="policy-evidence">
                              <summary>
                                View input, expectation & actual result
                              </summary>
                              <pre>
                                {JSON.stringify(
                                  {
                                    input: c.input,
                                    expected: c.expected,
                                    actual: {
                                      decision: c.decision,
                                      reason: c.reason,
                                    },
                                    observed: c.observed,
                                  },
                                  null,
                                  2,
                                )}
                              </pre>
                            </details>
                          )}
                        </span>
                        <strong>
                          {c.skipped
                            ? "Not applicable"
                            : c.passed
                              ? "Passed"
                              : "Failed"}
                        </strong>
                      </li>
                    ))}
                  </ul>
                  <HelpLink topic="guardrails">
                    What these checks actually test
                  </HelpLink>
                  <h3>Historical backtests</h3>
                  <HelpLink topic="backtests">
                    Where these results come from
                  </HelpLink>
                  <p className="builder-note">
                    Recorded exchange prices, before guardrails. These returns
                    are observations, not pass/fail scores.
                  </p>
                  {plan.report.market_data && (
                    <details className="source-details">
                      <summary>
                        Binance source, exact candles & provenance
                      </summary>
                      <p>
                        Fetched{" "}
                        {new Date(
                          plan.report.market_data.fetched_at * 1000,
                        ).toISOString()}{" "}
                        · {plan.report.market_data.market}
                      </p>
                      <code>{plan.report.market_data.snapshot_id}</code>
                      <p>
                        <a
                          href={
                            "/v1/agent-plans/" + plan.plan_id + "/market-data"
                          }
                          target="_blank"
                          rel="noreferrer"
                        >
                          Download candles & source metadata
                        </a>
                      </p>
                    </details>
                  )}
                  <div className="builder-simulations">
                    {plan.report.simulations.map((s) => (
                      <div key={s.dataset}>
                        <span>{s.dataset}</span>
                        {s.market_data && (
                          <small>
                            {new Date(
                              s.market_data.period_start * 1000,
                            ).toLocaleDateString()}{" "}
                            —{" "}
                            {new Date(
                              s.market_data.period_end * 1000,
                            ).toLocaleDateString()}
                          </small>
                        )}
                        <strong
                          className={s.metrics.return_pct < 0 ? "negative" : ""}
                        >
                          {s.metrics.return_pct > 0 ? "+" : ""}
                          {s.metrics.return_pct.toFixed(2)}%
                        </strong>
                        <small>
                          {s.metrics.trade_count} trades ·{" "}
                          {s.metrics.max_drawdown.toFixed(2)}% drawdown
                        </small>
                      </div>
                    ))}
                  </div>
                  <p className="builder-note">{plan.report.note}</p>
                  {plan.report.market_data && (
                    <div className="market-source">
                      <strong>
                        {plan.report.market_data.provider} ·{" "}
                        {plan.report.market_data.market}
                      </strong>
                      <span>
                        Retrieved{" "}
                        {new Date(
                          plan.report.market_data.fetched_at * 1000,
                        ).toLocaleString()}
                      </span>
                      <small>
                        Snapshot{" "}
                        {plan.report.market_data.snapshot_id.slice(0, 16)} ·
                        closed candles only
                      </small>
                    </div>
                  )}
                </>
              )}
              <div className="builder-actions">
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => setStep(1)}
                >
                  <ArrowLeft size={15} /> Edit guardrails
                </button>
                <button
                  className="primary"
                  disabled={busy || !plan?.report.ready}
                  onClick={() => {
                    setAcknowledged(false);
                    setStep(3);
                  }}
                >
                  Review deployment <ArrowRight size={15} />
                </button>
              </div>
            </>
          )}
          {step === 3 && plan && (
            <>
              <span className="builder-kicker">04 / YOUR DECISION</span>
              <h2>
                {plan.strategy_id
                  ? "Original deployment review"
                  : "Ready to deploy?"}
              </h2>
              <p>
                Review exactly what you are authorizing for{" "}
                <strong>{reviewed.name}</strong>.
              </p>
              <blockquote className="builder-goal">{reviewed.goal}</blockquote>
              <dl className="builder-review">
                <ReviewRow
                  label="Strategy"
                  value={
                    runners[reviewed.strategy_config.runner] +
                    " · " +
                    reviewed.market +
                    " · " +
                    reviewed.timeframe
                  }
                />
                <ReviewRow
                  label="Paper capital"
                  value={money(reviewed.starting_capital)}
                />
                <ReviewRow
                  label="Max position / trade"
                  value={
                    money(g.max_position_size) + " / " + money(g.max_trade_size)
                  }
                />
                <ReviewRow
                  label="Loss controls"
                  value={
                    g.max_daily_loss +
                    "% daily loss · " +
                    g.max_drawdown +
                    "% drawdown: block new buys"
                  }
                />
                <ReviewRow
                  label="Allowed actions"
                  value={
                    "Paper buy / sell " +
                    reviewed.market +
                    "; one spot position"
                  }
                />
                <ReviewRow
                  label="Human approval"
                  value={
                    g.human_approval_above === 0
                      ? "Required for every trade"
                      : "Required above " + money(g.human_approval_above)
                  }
                />
                <ReviewRow
                  label="Forbidden"
                  value="Leverage · withdrawals · short selling"
                />
                <ReviewRow
                  label="Test result"
                  value={
                    plan.report.passed +
                    "/" +
                    plan.report.total +
                    " admission checks passed · 3 historical backtests"
                  }
                />
                {plan.report.replay_market_data && (
                  <ReviewRow
                    label="Paper replay period"
                    value={
                      new Date(
                        plan.report.replay_market_data.period_start * 1000,
                      ).toLocaleString() +
                      " — " +
                      new Date(
                        plan.report.replay_market_data.period_end * 1000,
                      ).toLocaleString()
                    }
                  />
                )}
                <ReviewRow label="Visibility" value="Private workspace" />
              </dl>
              <div className="builder-boundary">
                <ShieldCheck size={20} />
                <div>
                  <strong>What happens when you deploy</strong>
                  <p>
                    Tracy creates one agent, its reviewed strategy and a paper
                    deployment. You advance the replay from the strategy page;
                    permitted fills produce signed proofs. No real funds or
                    public listing.
                  </p>
                </div>
              </div>
              {!plan.strategy_id && (
                <label className="builder-confirm">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    onChange={(e) => setAcknowledged(e.target.checked)}
                    disabled={busy}
                  />
                  <span>
                    I reviewed the intent, limits and test results. I authorize
                    this paper deployment.
                  </span>
                </label>
              )}
              <div className="builder-actions">
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => setStep(2)}
                >
                  <ArrowLeft size={15} /> Test results
                </button>
                {plan.strategy_id ? (
                  <Link
                    className="primary"
                    to={"/strategies/" + plan.strategy_id}
                  >
                    Open deployed agent <ArrowRight size={16} />
                  </Link>
                ) : (
                  <button
                    className="primary"
                    disabled={busy || !acknowledged || !plan.report.ready}
                    onClick={() => void deploy()}
                  >
                    {busy ? "Creating your agent…" : "Deploy paper agent"}
                    <ArrowRight size={16} />
                  </button>
                )}
              </div>
            </>
          )}
        </section>
        <aside className="builder-aside">
          <div className="builder-aside-icon">
            <ShieldCheck size={24} />
          </div>
          <h3>Permission comes first.</h3>
          <p>Your agent is the result of a reviewed plan.</p>
          <ol>
            <li>
              <strong>Intent</strong>
              <span>A clear job and a defined market.</span>
            </li>
            <li>
              <strong>Boundaries</strong>
              <span>Limits decide which actions are allowed.</span>
            </li>
            <li>
              <strong>Evidence</strong>
              <span>
                Test results before deployment. Signed proofs after execution.
              </span>
            </li>
          </ol>
          <div className="builder-draft">
            <Sparkles size={15} />
            <span>
              {plan?.strategy_id
                ? "Already deployed · safe to reopen"
                : "Draft only · no agent created yet"}
            </span>
          </div>
        </aside>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step = "any",
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number | string;
  onChange: (n: number) => void;
}) {
  return (
    <label>
      {label}
      <input
        type="number"
        required
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? NaN : Number(e.target.value))
        }
      />
    </label>
  );
}
function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
