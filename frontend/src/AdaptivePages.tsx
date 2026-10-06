import { BundlePayments } from "./DevnetWallet";
import { BundleIntelligence } from "./AdaptiveProduct";
import { EvolutionPanel } from "./EvolutionPanel";
import { useEffect, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { api, download } from "./api";
import { HelpLink } from "./Copilot";
import { agentDefaults } from "./agent-config";
import "./adaptive.css";

type Program = {
  kind: string;
  lookback: number;
  threshold_bps: number;
  exit_after_bars: number;
  fast: number;
  slow: number;
};
type Blueprint = {
  name: string;
  intent: string;
  market: string;
  timeframe: string;
  capital: number;
  allocation_pct: number;
  fee_bps: number;
  slippage_bps: number;
  program: Program;
  guardrails: ReturnType<typeof agentDefaults>["guardrails"];
  learning: {
    expected_return_pct: number;
    horizon_bars: number;
    invalidation_pct: number;
    minimum_samples: number;
  };
  pine_source: string | null;
};
type Metrics = {
  pnl: number;
  return_pct: number;
  max_drawdown: number;
  closed_trade_count: number;
  fees: number;
  position_value: number;
};
type State = {
  schema?: string;
  apr?: {
    probability: number;
    positive: number;
    negative: number;
    ignored: number;
  }[];
  active_arm: number;
  observed_until: number;
  personal_closed_trades: number;
  inherited_from?: string;
  arms: {
    value: number;
    alpha: number;
    beta: number;
    closed_trades: number;
    net_pnl: number;
  }[];
};
type Report = {
  run_id: string;
  candidate_arm: number;
  resulting_revision: number;
  gate: { passed: boolean; checks: Record<string, boolean> };
  training: { metrics: Metrics };
  baseline: { metrics: Metrics };
  incumbent: { metrics: Metrics };
  candidate: { metrics: Metrics };
  validation_start: number;
  validation_end: number;
  note: string;
};
type Envelope<T> = {
  hash: string;
  public_key: string;
  signature: string;
  body: T;
};
type Agent = {
  agent_id: string;
  name: string;
  revision: number;
  strategy_hash: string;
  strategy_apr: { blueprint: Blueprint };
  state: State;
  runs: Envelope<Report>[];
  review_report?: Envelope<Report>;
  bundles: { bundle_id: string; listed: boolean; revision: number }[];
  forward_runs?: { forward_id: string; status: string }[];
};
type Bundle = {
  bundle_id: string;
  listed: boolean;
  envelope: Envelope<{
    name: string;
    revision: number;
    agent_apr: State;
    strategy_apr: { blueprint: Blueprint };
    evidence: Envelope<Report>;
    transfer: string;
  }>;
  anchor: null | { status: string; explorer?: string; reason?: string };
};
type Forward = {
  forward_id: string;
  status: string;
  started_at: number;
  ends_at: number;
  last_error: string | null;
  stop_reason?: string;
  observations: number;
  baseline_metrics: Metrics;
  agent_metrics: Metrics;
  proof_valid: boolean;
  last_quote: { bid: number; ask: number; timestamp: number };
  execution: string;
};
const stamp = (n: number) => new Date(n * 1000).toLocaleString();
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const defaults = (): Blueprint => ({
  name: "BTC learning agent",
  intent:
    "Learn bounded BTC entry thresholds while keeping my risk limits unchanged.",
  market: "BTC/USDC",
  timeframe: "1h",
  capital: 1000,
  allocation_pct: 10,
  fee_bps: 10,
  slippage_bps: 10,
  program: {
    kind: "momentum",
    lookback: 7,
    threshold_bps: 60,
    exit_after_bars: 12,
    fast: 5,
    slow: 20,
  },
  pine_source: null,
  learning: {
    expected_return_pct: 0.5,
    horizon_bars: 4,
    invalidation_pct: -1.5,
    minimum_samples: 20,
  },
  guardrails: {
    max_position_size: 150,
    max_trade_size: 150,
    max_daily_loss: 0.5,
    max_drawdown: 1.5,
    allowed_tokens: ["BTC", "USDC"],
    allowed_markets: ["BTC/USDC"],
    max_open_positions: 1,
    human_approval_above: 150,
  },
});
function MetricsTable({ rows }: { rows: [string, Metrics][] }) {
  return (
    <div className="adaptive-scroll">
      <table>
        <thead>
          <tr>
            <th>Policy</th>
            <th>Net PnL (USDC)</th>
            <th>Return</th>
            <th>Max drawdown</th>
            <th>Closed trades</th>
            <th>Fees</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, m]) => (
            <tr key={name}>
              <td>{name}</td>
              <td>{m.pnl.toFixed(4)}</td>
              <td>{m.return_pct.toFixed(3)}%</td>
              <td>{m.max_drawdown.toFixed(3)}%</td>
              <td>{m.closed_trade_count}</td>
              <td>{m.fees.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Posterior({ state }: { state: State }) {
  return (
    <>
      <div className="adaptive-scroll">
        <table>
          <thead>
            <tr>
              <th>Entry filter</th>
              <th>
                {state.apr
                  ? "Supported / failed theses"
                  : "Legacy positive / other exits"}
              </th>
              <th>Posterior mean</th>
              <th>Closed trades</th>
              <th>Active</th>
            </tr>
          </thead>
          <tbody>
            {state.arms.map((a, i) => (
              <tr key={i}>
                <td>{a.value} bps</td>
                <td>
                  {state.apr?.[i].positive ?? a.alpha - 1} /{" "}
                  {state.apr?.[i].negative ?? a.beta - 1}
                </td>
                <td>
                  {(
                    100 *
                    (state.apr?.[i].probability ?? a.alpha / (a.alpha + a.beta))
                  ).toFixed(1)}
                  %
                </td>
                <td>{a.closed_trades}</td>
                <td>{state.active_arm === i ? "Active" : "Candidate"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Counts describe observed evidence (APR v2 uses attributed horizons);
        they are not a forecast of future profitability. Personal closed trades:{" "}
        {state.personal_closed_trades}.
      </p>
      {state.inherited_from && (
        <p>
          Inherited learning from bundle <code>{state.inherited_from}</code>.
          Your capital and personal trading history start fresh.
        </p>
      )}
    </>
  );
}
export function AdaptiveLab() {
  const navigate = useNavigate();
  const [query] = useSearchParams();
  const [items, setItems] = useState<
    { agent_id: string; name: string; revision: number }[]
  >([]);
  const [value, setValue] = useState<Blueprint>(defaults);
  const [pine, setPine] = useState("");
  const [example, setExample] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [proposal, setProposal] = useState<{
    proposal: Blueprint;
    explanation: string;
    questions: string[];
    changes: { field: string; before: unknown; after: unknown }[];
  } | null>(null);
  useEffect(() => {
    api<{ items: typeof items }>("/adaptive/agents")
      .then((r) => setItems(r.items))
      .catch((e) => setError(errorText(e)));
    api<{ pine_example: string }>("/adaptive/capabilities")
      .then((r) => setExample(r.pine_example))
      .catch((e) => setError(errorText(e)));
  }, []);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const field = (k: keyof Blueprint, n: unknown) => {
    setValue((v) => ({ ...v, [k]: n }));
    setReview(false);
  };
  const program = (k: keyof Program, n: string | number) => {
    setValue((v) => ({
      ...v,
      pine_source: null,
      program: { ...v.program, [k]: n },
    }));
    setReview(false);
  };
  const numeric = (label: string, n: number, change: (n: number) => void) => (
    <label>
      {label}
      <input
        type="number"
        step="any"
        value={n}
        onChange={(e) => change(Number(e.target.value))}
      />
    </label>
  );
  return (
    <div className="adaptive-page">
      <header>
        <div className="eyebrow">ADAPTIVE LAB / DEVNET</div>
        <h1>
          Your strategy is the baseline.
          <br />
          Your agent learns.
        </h1>
        <p>
          Train bounded entry rules, compare on unseen data and publish a
          reproducible bundle. All trading uses virtual capital.
        </p>
        <HelpLink topic="adaptive" />
      </header>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      {query.get("strategy") && (
        <section className="panel editor">
          <h2>Start from an existing strategy</h2>
          <p>
            Import its exact rules and risk limits into a separate learning
            instance.
          </p>
          <button
            disabled={busy}
            onClick={() =>
              void work(async () => {
                const a = await api<Agent>("/adaptive/from-strategy", {
                  method: "POST",
                  body: JSON.stringify({
                    strategy_id: query.get("strategy"),
                    version: query.get("version")
                      ? Number(query.get("version"))
                      : null,
                    name: value.name,
                  }),
                });
                navigate("/lab/" + a.agent_id);
              })
            }
          >
            Import reviewed strategy
          </button>
        </section>
      )}
      <section className="panel editor">
        <h2>1. Rules and intent</h2>
        <div className="adaptive-fields">
          <label>
            Name
            <input
              value={value.name}
              onChange={(e) => field("name", e.target.value)}
            />
          </label>
          <label>
            Template
            <select
              value={value.program.kind}
              onChange={(e) => program("kind", e.target.value)}
            >
              <option value="momentum">Momentum</option>
              <option value="mean_reversion">Mean reversion</option>
              <option value="sma_cross">SMA crossover</option>
              <option value="ema_cross">EMA crossover</option>
            </select>
          </label>
          <label>
            Market
            <select
              value={value.market}
              onChange={(e) => {
                const market = e.target.value;
                setValue((v) => ({
                  ...v,
                  market,
                  guardrails: {
                    ...v.guardrails,
                    allowed_markets: [market],
                    allowed_tokens: market.split("/"),
                  },
                }));
                setReview(false);
              }}
            >
              {["BTC/USDC", "ETH/USDC", "SOL/USDC"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            Timeframe
            <select
              value={value.timeframe}
              onChange={(e) => field("timeframe", e.target.value)}
            >
              {["1h", "4h", "1d"].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Intent
          <textarea
            rows={3}
            value={value.intent}
            onChange={(e) => field("intent", e.target.value)}
          />
        </label>
        <button
          disabled={busy || value.intent.length < 10}
          onClick={() =>
            void work(async () => {
              setProposal(
                await api("/adaptive/build", {
                  method: "POST",
                  body: JSON.stringify({ intent: value.intent, draft: value }),
                }),
              );
            })
          }
        >
          Suggest rules with Gemini
        </button>
        {proposal && (
          <section>
            <h3>Review AI proposal</h3>
            <p>{proposal.explanation}</p>
            {proposal.changes.map((c) => (
              <p key={c.field}>
                {c.field}: {JSON.stringify(c.before)} →{" "}
                {JSON.stringify(c.after)}
              </p>
            ))}
            {proposal.questions.map((q) => (
              <p key={q}>{q}</p>
            ))}
            <button
              disabled={proposal.questions.length > 0}
              onClick={() => {
                setValue(proposal.proposal);
                setProposal(null);
                setReview(false);
              }}
            >
              Apply reviewed proposal to draft
            </button>
          </section>
        )}
        <p>
          For AI-assisted strategy creation,{" "}
          <Link to="/agents/new">describe your strategy to Tracy</Link>, review
          it, then choose “Learn from this strategy” on its detail page.
        </p>
        <details>
          <summary>Import supported Pine Script v6</summary>
          <p>
            Supported: long-only SMA/EMA crossover, integer inputs, named
            signals and simple plots. Other code is rejected. Capital and risk
            settings come from the form below.
          </p>
          {["sma_cross", "ema_cross"].includes(value.program.kind) && (
            <button
              disabled={busy}
              onClick={() =>
                void work(async () => {
                  const r = await api<{ source: string }>(
                    "/adaptive/export-pine",
                    { method: "POST", body: JSON.stringify(value.program) },
                  );
                  setPine(r.source);
                  setNotes([
                    "Exported signal rules. Risk controls and learned probabilities stay in your Bundle.",
                  ]);
                })
              }
            >
              Export reviewed rules as Pine
            </button>
          )}
          <button className="secondary" onClick={() => setPine(example)}>
            Load supported example
          </button>
          <textarea
            aria-label="Pine source"
            className="adaptive-code"
            rows={10}
            value={pine}
            onChange={(e) => setPine(e.target.value)}
          />
          <button
            disabled={busy || !pine}
            onClick={() =>
              void work(async () => {
                const result = await api<{ program: Program; notes: string[] }>(
                  "/adaptive/import-pine",
                  { method: "POST", body: JSON.stringify({ source: pine }) },
                );
                setValue((v) => ({
                  ...v,
                  program: result.program,
                  pine_source: pine,
                }));
                setNotes(result.notes);
                setReview(false);
              })
            }
          >
            Validate and import Pine
          </button>
          {notes.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </details>
        <div className="adaptive-fields">
          {["sma_cross", "ema_cross"].includes(value.program.kind) ? (
            <>
              {numeric("Fast SMA", value.program.fast, (n) =>
                program("fast", n),
              )}
              {numeric("Slow SMA", value.program.slow, (n) =>
                program("slow", n),
              )}
            </>
          ) : (
            <>
              {numeric("Lookback bars", value.program.lookback, (n) =>
                program("lookback", n),
              )}
              {numeric(
                "Entry threshold (bps)",
                value.program.threshold_bps,
                (n) => program("threshold_bps", n),
              )}
              {numeric("Exit after bars", value.program.exit_after_bars, (n) =>
                program("exit_after_bars", n),
              )}
            </>
          )}
        </div>
      </section>
      <section className="panel editor">
        <h2>2. Guardrails — fixed throughout learning</h2>
        <div className="adaptive-fields">
          {numeric("Virtual capital (USDC)", value.capital, (n) =>
            field("capital", n),
          )}
          {numeric(
            "Capital per entry (%) · max 25",
            value.allocation_pct,
            (n) => field("allocation_pct", n),
          )}
          {numeric("Fee per side (bps)", value.fee_bps, (n) =>
            field("fee_bps", n),
          )}
          {numeric("Slippage per side (bps)", value.slippage_bps, (n) =>
            field("slippage_bps", n),
          )}
          {(
            [
              ["max_position_size", "Max position (USDC)"],
              ["max_trade_size", "Max entry (USDC)"],
              ["human_approval_above", "Automatic entry allowance (USDC)"],
              ["max_daily_loss", "Daily loss trigger (%)"],
              ["max_drawdown", "Drawdown trigger (%)"],
            ] as const
          ).map(([k, label]) => (
            <div key={k}>
              {numeric(label, value.guardrails[k], (n) =>
                field("guardrails", { ...value.guardrails, [k]: n }),
              )}
            </div>
          ))}
        </div>
        <p>
          One long spot position. No leverage, withdrawals or shorting. Loss
          triggers block new entries and request an exit at the next available
          quote; they do not guarantee a maximum loss. Reducing an existing
          position is allowed above entry limits.
        </p>
      </section>
      <section className="panel editor">
        <h2>3. Review the learning boundary</h2>
        <div className="adaptive-fields">
          {(
            [
              ["expected_return_pct", "Expected horizon return (%)"],
              ["horizon_bars", "Evaluation horizon (complete bars)"],
              ["invalidation_pct", "Thesis invalidation (%)"],
              ["minimum_samples", "Minimum eligible samples per rule"],
            ] as const
          ).map(([key, label]) => (
            <div key={key}>
              {numeric(label, value.learning[key], (n) =>
                field("learning", { ...value.learning, [key]: n }),
              )}
            </div>
          ))}
        </div>
        <p>
          {["sma_cross", "ema_cross"].includes(value.program.kind)
            ? "Agent can filter SMA-cross entries by 0, 5 or 10 bps of separation."
            : `Agent can choose entry thresholds of ${value.program.threshold_bps}, ${value.program.threshold_bps * 0.5} or ${value.program.threshold_bps * 1.5} bps.`}{" "}
          Capital, risk limits, fees and exit rules stay fixed.
        </p>
        <p>
          Training explores these variants with virtual capital. Activation
          needs an explicit review after the holdout gate. No real orders will
          be sent.
        </p>
        <label className="adaptive-check">
          <input
            type="checkbox"
            checked={review}
            onChange={(e) => setReview(e.target.checked)}
          />
          I reviewed these rules, risk exits and learning bounds.
        </label>
        <button
          disabled={busy || !review}
          onClick={() =>
            void work(async () => {
              const a = await api<Agent>("/adaptive/agents", {
                method: "POST",
                body: JSON.stringify(value),
              });
              navigate("/lab/" + a.agent_id);
            })
          }
        >
          {busy ? "Working…" : "Create learning instance"}
        </button>
      </section>
      <section className="panel editor">
        <h2>Your learning instances</h2>
        {items.length ? (
          items.map((a) => (
            <p key={a.agent_id}>
              <Link to={"/lab/" + a.agent_id}>{a.name} →</Link> · revision{" "}
              {a.revision}
            </p>
          ))
        ) : (
          <p>No learning instances yet.</p>
        )}
      </section>
    </div>
  );
}

export function AdaptiveAgentPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [start, setStart] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [policyMode, setPolicyMode] = useState("adaptive");
  const load = () => api<Agent>("/adaptive/agents/" + id).then(setAgent);
  useEffect(() => {
    void load().catch((e) => setError(errorText(e)));
  }, [id]);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (!agent)
    return (
      <div className="adaptive-page">
        <h1>Learning instance</h1>
        {error || "Loading…"}
      </div>
    );
  const report = agent.runs[0] || agent.review_report;
  const bp = agent.strategy_apr.blueprint;
  return (
    <div className="adaptive-page">
      <header>
        <Link to="/lab">← Adaptive lab</Link>
        <h1>{agent.name}</h1>
        <p>
          Revision {agent.revision} · {bp.market} · {bp.timeframe} ·{" "}
          {bp.capital} virtual USDC
        </p>
        <HelpLink topic="adaptive" />
      </header>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="panel editor">
        <h2>Immutable baseline</h2>
        <p>{bp.intent}</p>
        <code className="adaptive-hash">{agent.strategy_hash}</code>
        <details>
          <summary>Rules, costs and guardrails</summary>
          <pre>{JSON.stringify(bp, null, 2)}</pre>
        </details>
      </section>
      <section className="panel editor">
        <h2>Agent learning state</h2>
        <Posterior state={agent.state} />
      </section>
      <EvolutionPanel agentId={agent.agent_id} />
      <section className="panel editor">
        <h2>Train → validate → review</h2>
        <p>
          576 closed candles for training, then 288 separate candles for frozen
          validation. Both portfolios use the same market, period, capital,
          costs and risk rules. Previously observed data cannot be learned
          twice.
        </p>
        <label>
          Period start, UTC (optional)
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <button
          disabled={busy}
          onClick={() =>
            void work(async () => {
              await api("/adaptive/agents/" + id + "/experiments", {
                method: "POST",
                body: JSON.stringify({
                  request_id: crypto.randomUUID(),
                  expected_revision: agent.revision,
                  period_start: start
                    ? Math.floor(new Date(start + "Z").getTime() / 1000)
                    : null,
                }),
              });
              setAccepted(false);
            })
          }
        >
          {busy ? "Working…" : "Run historical experiment"}
        </button>
        {report && (
          <>
            <p>
              Validation: {stamp(report.body.validation_start)} →{" "}
              {stamp(report.body.validation_end)} (local display time).
            </p>
            <MetricsTable
              rows={[
                ["Original baseline", report.body.baseline.metrics],
                ["Current policy", report.body.incumbent.metrics],
                ["Learned candidate", report.body.candidate.metrics],
              ]}
            />
            <h3>
              {report.body.gate.passed
                ? "Candidate passed this holdout"
                : "Keep the current policy"}
            </h3>
            <ul>
              {Object.entries(report.body.gate.checks).map(([k, v]) => (
                <li key={k}>
                  {v ? "Passed" : "Not passed"} — {k.replaceAll("_", " ")}
                </li>
              ))}
            </ul>
            <p>{report.body.note}</p>
            <label className="adaptive-check">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(e) => setAccepted(e.target.checked)}
              />
              I reviewed the candidate, costs, sample size and comparison.
            </label>
            <button
              disabled={
                busy ||
                !accepted ||
                !report.body.gate.passed ||
                report.body.resulting_revision !== agent.revision
              }
              onClick={() =>
                void work(async () => {
                  await api("/adaptive/agents/" + id + "/activate", {
                    method: "POST",
                    body: JSON.stringify({
                      expected_revision: agent.revision,
                      report_hash: report.hash,
                    }),
                  });
                })
              }
            >
              Activate reviewed candidate
            </button>
            <button
              className="secondary"
              onClick={() => download(report, "learning-report.json")}
            >
              Download signed report
            </button>
          </>
        )}
      </section>
      <section className="panel editor">
        <h2>Observe the next 24 hours</h2>
        <p>
          Run the original baseline and your current policy side by side on new
          quotes. Orders and capital are virtual. Choose frozen comparison or
          bounded learning from attributed horizon outcomes. Risk limits stay
          fixed.
        </p>
        <label>
          Policy mode
          <select
            value={policyMode}
            onChange={(e) => setPolicyMode(e.target.value)}
          >
            <option value="adaptive">
              Adaptive — attributed outcomes may update APR
            </option>
            <option value="frozen">
              Frozen — keep this policy for the comparison
            </option>
          </select>
        </label>
        <button
          disabled={busy || !report || !accepted}
          onClick={() =>
            void work(async () => {
              const reviewed = await api<Agent>(
                "/adaptive/agents/" + id + "/review",
                {
                  method: "POST",
                  body: JSON.stringify({
                    expected_revision: agent.revision,
                    report_hash: report!.hash,
                    policy_mode: policyMode,
                    acknowledged: true,
                  }),
                },
              );
              const r = await api<Forward>(
                "/adaptive/agents/" +
                  id +
                  "/forward?revision=" +
                  reviewed.revision,
                { method: "POST" },
              );
              navigate("/lab/forward/" + r.forward_id);
            })
          }
        >
          Start 24-hour forward paper comparison
        </button>
        {agent.forward_runs?.map((r) => (
          <p key={r.forward_id}>
            <Link to={"/lab/forward/" + r.forward_id}>
              {r.status} → view experiment
            </Link>
          </p>
        ))}
      </section>
      <section className="panel editor">
        <h2>Freeze a transferable Bundle</h2>
        <p>
          Save the immutable rules, current learning state and experiment
          evidence. Freezing is private. Publishing is a separate step.
        </p>
        <button
          disabled={busy || !report}
          onClick={() =>
            void work(async () => {
              const b = await api<Bundle>(
                "/adaptive/agents/" +
                  id +
                  "/bundles?revision=" +
                  agent.revision,
                { method: "POST" },
              );
              navigate("/lab/bundles/" + b.bundle_id);
            })
          }
        >
          Freeze this revision
        </button>
        {agent.bundles.map((b) => (
          <p key={b.bundle_id}>
            <Link to={"/lab/bundles/" + b.bundle_id}>
              Revision {b.revision} · {b.listed ? "Published" : "Private"} →
            </Link>
          </p>
        ))}
      </section>
    </div>
  );
}

export function BundlePage({ publicView = false }: { publicView?: boolean }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [disclose, setDisclose] = useState(false);
  const load = () =>
    api<Bundle>(
      (publicView ? "/public/bundles/" : "/adaptive/bundles/") + id,
    ).then(setBundle);
  useEffect(() => {
    void load().catch((e) => setError(errorText(e)));
  }, [id, publicView]);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (!bundle)
    return (
      <div className="adaptive-page">
        <h1>Bundle</h1>
        {error || "Loading…"}
      </div>
    );
  const b = bundle.envelope.body;
  return (
    <div className="adaptive-page">
      <header>
        <Link to="/bundles">← Bundle marketplace</Link>
        <h1>{b.name}</h1>
        <p>
          Frozen revision {b.revision} · Paper trading / Devnet evidence · Free
          preview
        </p>
        <HelpLink topic="bundles" />
      </header>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      <section className="panel editor">
        <h2>Strategy + agent + learned state</h2>
        <p>{b.transfer}</p>
        <Posterior state={b.agent_apr} />
        <details>
          <summary>Original strategy APR</summary>
          <pre>{JSON.stringify(b.strategy_apr, null, 2)}</pre>
        </details>
        <MetricsTable
          rows={[
            ["Baseline holdout", b.evidence.body.baseline.metrics],
            ["Candidate holdout", b.evidence.body.candidate.metrics],
          ]}
        />
        <p>
          {b.evidence.body.gate.passed
            ? "Candidate passed the recorded gate; inspect the active arm to see whether it was activated."
            : "Candidate did not pass the recorded gate. This bundle does not claim an improvement."}
        </p>
        <button
          className="secondary"
          onClick={() => download(bundle.envelope, "tracy-bundle.json")}
        >
          Download signed Bundle
        </button>
      </section>
      <section className="panel editor">
        <h2>Use this work</h2>
        <button
          disabled={busy}
          onClick={() =>
            void work(async () => {
              const first = await api<Agent>(`/adaptive/bundles/${id}/clone`, {
                method: "POST",
                body: JSON.stringify({ name: b.name + " · A", mode: "bundle" }),
              });
              const second = await api<Agent>(`/adaptive/bundles/${id}/clone`, {
                method: "POST",
                body: JSON.stringify({ name: b.name + " · B", mode: "bundle" }),
              });
              navigate(
                `/lab/compare?first=${first.agent_id}&second=${second.agent_id}`,
              );
            })
          }
        >
          Create two independent clones and compare
        </button>
        <p>
          Create a separate instance with the reviewed configuration shown
          above. No balance, credentials or personal trade history are copied.
          Inherited learning retains its observed-data cutoff.
        </p>
        {(["strategy", "bundle"] as const).map((mode) => (
          <button
            disabled={busy}
            key={mode}
            onClick={() =>
              void work(async () => {
                const a = await api<Agent>(
                  "/adaptive/bundles/" + id + "/clone",
                  {
                    method: "POST",
                    body: JSON.stringify({
                      name:
                        b.name +
                        (mode === "bundle"
                          ? " · learned copy"
                          : " · fresh baseline"),
                      mode,
                    }),
                  },
                );
                navigate("/lab/" + a.agent_id);
              })
            }
          >
            {mode === "bundle"
              ? "Create instance with learned state"
              : "Create instance from rules only"}
          </button>
        ))}
        <p>
          Sign in to create an instance.{" "}
          <Link to="/lab">Open your workspace →</Link>
        </p>
      </section>
      {id && <BundlePayments id={id} owner={!publicView} />}
      {publicView && id && <BundleIntelligence id={id} />}
      <section className="panel editor">
        <h2>Solana Devnet proof</h2>
        <code className="adaptive-hash">{bundle.envelope.hash}</code>
        <p>
          {bundle.anchor
            ? bundle.anchor.status +
              " — " +
              (bundle.anchor.reason || "Waiting for confirmation")
            : "No on-chain anchor yet. The downloadable record is signed by Tracy."}
        </p>
        {bundle.anchor?.explorer && (
          <a href={bundle.anchor.explorer} target="_blank" rel="noreferrer">
            Inspect transaction on Solana Explorer →
          </a>
        )}
        <p>
          A memo timestamps the Bundle hash. It does not certify returns or
          exchange execution. Only test SOL pays the network fee.
        </p>
        {!publicView && (
          <button
            disabled={busy}
            onClick={() =>
              void work(async () => {
                await api("/adaptive/bundles/" + id + "/anchor", {
                  method: "POST",
                });
              })
            }
          >
            Record / verify Devnet memo
          </button>
        )}
      </section>
      {!publicView && (
        <section className="panel editor">
          <h2>
            {bundle.listed ? "Manage publication" : "Publish this Bundle"}
          </h2>
          <p>
            Publication makes the strategy source, risk configuration, learned
            counts, training results and signed evidence publicly downloadable.
          </p>
          <label className="adaptive-check">
            <input
              type="checkbox"
              checked={disclose}
              onChange={(e) => setDisclose(e.target.checked)}
            />
            I reviewed the public disclosure.
          </label>
          <button
            disabled={busy || (!bundle.listed && !disclose)}
            onClick={() =>
              void work(async () => {
                await api("/adaptive/bundles/" + id + "/publication", {
                  method: "PUT",
                  body: JSON.stringify({ listed: !bundle.listed }),
                });
              })
            }
          >
            {bundle.listed ? "Unpublish" : "Publish to Bundle marketplace"}
          </button>
          {bundle.listed && (
            <Link to={"/bundles/" + id}>View public listing →</Link>
          )}
        </section>
      )}
    </div>
  );
}

export function BundleMarketplace() {
  const [items, setItems] = useState<
    {
      bundle_id: string;
      name: string;
      market: string;
      revision: number;
      gate: { passed: boolean };
    }[]
  >([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ items: typeof items }>("/public/bundles")
      .then((r) => setItems(r.items))
      .catch((e) => setError(errorText(e)));
  }, []);
  return (
    <div className="adaptive-page">
      <header>
        <div className="eyebrow">
          MARKETPLACE / STRATEGIES AND LEARNED AGENTS
        </div>
        <h1>
          Start with the recipe.
          <br />
          Or bring the experience.
        </h1>
        <p>
          Inspect an immutable strategy and its agent's learned state. All
          current listings are free paper experiments.
        </p>
        <Link className="primary" to="/lab">
          Build and train an agent
        </Link>{" "}
        <HelpLink topic="bundles" />
      </header>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      {items.length ? (
        items.map((b) => (
          <section className="panel editor" key={b.bundle_id}>
            <h2>{b.name}</h2>
            <p>
              {b.market} · revision {b.revision} ·{" "}
              {b.gate.passed
                ? "Candidate passed recorded holdout"
                : "No validated improvement claimed"}
            </p>
            <Link to={"/bundles/" + b.bundle_id}>
              Inspect rules, learning and evidence →
            </Link>
          </section>
        ))
      ) : (
        <section className="panel editor">
          <h2>No published Bundles yet</h2>
          <p>
            Create a learning instance, run an experiment, freeze a revision and
            explicitly publish it.
          </p>
        </section>
      )}
    </div>
  );
}

export function ForwardPage() {
  const { id } = useParams();
  const [run, setRun] = useState<Forward | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api<Forward>("/adaptive/forward/" + id).then(setRun);
  useEffect(() => {
    void load().catch((e) => setError(errorText(e)));
    const timer = setInterval(
      () => void load().catch((e) => setError(errorText(e))),
      15000,
    );
    return () => clearInterval(timer);
  }, [id]);
  const act = async (action: string) => {
    setBusy(true);
    setError("");
    try {
      await api("/adaptive/forward/" + id + "/" + action, { method: "POST" });
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="adaptive-page">
      <header>
        <Link to="/lab">← Adaptive lab</Link>
        <h1>Forward paper experiment</h1>
        <HelpLink topic="adaptive" />
      </header>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      {run && (
        <>
          <section className="panel editor">
            <h2>{run.status}</h2>
            <p>
              {stamp(run.started_at)} → {stamp(run.ends_at)} (local time)
            </p>
            <p>{run.execution}</p>
            <p>
              {run.observations} quote observations · Signed event chain:{" "}
              {run.proof_valid ? "verified" : "not verified"}
            </p>
            <p>
              Last quote: bid {run.last_quote.bid}, ask {run.last_quote.ask},
              received {stamp(run.last_quote.timestamp)}.
            </p>
            {run.last_error && <div className="error">{run.last_error}</div>}
            {run.stop_reason && <p>{run.stop_reason}</p>}
            <MetricsTable
              rows={[
                ["Original baseline", run.baseline_metrics],
                ["Your current policy", run.agent_metrics],
              ]}
            />
            <p>
              Open inventory at mark: baseline{" "}
              {run.baseline_metrics.position_value.toFixed(2)} USDC; agent{" "}
              {run.agent_metrics.position_value.toFixed(2)} USDC. Unrealized PnL
              does not include a future closing fee.
            </p>
            <button
              disabled={busy || run.status === "COMPLETED"}
              onClick={() => void act("refresh")}
            >
              Check new market data
            </button>
            <button
              className="secondary"
              disabled={busy || run.status === "COMPLETED"}
              onClick={() => void act("stop")}
            >
              Stop and close virtual positions
            </button>
            <button
              className="secondary"
              onClick={() => download(run, "forward-paper-report.json")}
            >
              Download evidence
            </button>
          </section>
        </>
      )}
    </div>
  );
}
