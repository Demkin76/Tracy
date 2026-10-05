import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Agent } from "./api";
import { useApp } from "./app-context";
import { ErrorNotice, err, Status } from "./PublicPages";
import type { Strategy } from "./LifecyclePages";

function useData<T>(path: string, poll = false) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState("");
  const load = async () => {
    try {
      setData(await api<T>(path));
      setError("");
    } catch (e) {
      setError(err(e));
    }
  };
  useEffect(() => {
    void load();
    if (poll) {
      const timer = setInterval(() => void load(), 15000);
      return () => clearInterval(timer);
    }
  }, [path, poll]);
  return { data, error, load };
}
const detail = (s: Strategy, tab: string) =>
  "/strategies/" + s.strategy_id + "?tab=" + encodeURIComponent(tab);
const amount = (n: number | null | undefined) =>
  n == null
    ? "—"
    : n.toLocaleString("en-US", { maximumFractionDigits: 2 }) + " USDC";
const pct = (n: number | null | undefined) =>
  n == null ? "—" : n.toFixed(2) + "%";
function Header({
  title,
  text,
  children,
}: {
  title: string;
  text: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">TRACY WORKSPACE</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {children}
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <section className="panel editor">
      <h2>No records yet</h2>
      <p>{text}</p>
      <Link className="primary" to="/">
        Explore agents →
      </Link>
      <p>
        Developing an agent?{" "}
        <Link to="/developers">Open developer studio →</Link>
      </p>
    </section>
  );
}

export function StrategiesPage() {
  const { data, error } = useData<{ items: Strategy[] }>("/strategies");
  const [archived, setArchived] = useState(false);
  const items =
    data?.items.filter((s) => archived || s.status !== "ARCHIVED") || [];
  return (
    <>
      <Header
        title="My strategies"
        text="Your trading recipes: versions, tests and marketplace publication. Each running agent uses its own reviewed copy."
      >
        <Link className="primary" to="/agents/new">
          Describe a new recipe
        </Link>
      </Header>
      <ErrorNotice error={error} />
      <label className="archive-filter">
        <input
          type="checkbox"
          checked={archived}
          onChange={(e) => setArchived(e.target.checked)}
        />{" "}
        Include archived strategies
      </label>
      {!!items.length && (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Market / runner</th>
                <th>Version</th>
                <th>State</th>
                <th>Visibility</th>
                <th>Configuration</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.strategy_id}>
                  <td>
                    <strong>{s.name}</strong>
                    <small className="section-subtext">{s.agent_name}</small>
                  </td>
                  <td>
                    {s.market}
                    <small className="section-subtext">
                      {s.strategy_config.runner.replaceAll("_", " ")}
                    </small>
                  </td>
                  <td>v{s.version}</td>
                  <td>
                    <Status value={s.status} />
                  </td>
                  <td>
                    {s.listed ? "Published" : "Private"}
                    <small className="section-subtext">
                      <Link to={"/strategies/" + s.strategy_id + "?publish=1"}>
                        {s.listed ? "Manage listing" : "Publish agent"}
                      </Link>
                    </small>
                  </td>
                  <td>
                    <Link to={detail(s, "Versions")}>Versions & recipe →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {data && !items.length && (
        <Empty text="A strategy appears after its intent, guardrails and tests have been reviewed." />
      )}
    </>
  );
}

export function MonitoringPage() {
  const strategies = useData<{ items: Strategy[] }>("/strategies", true);
  const queue = useData<{
    items: { intent_id: string; strategy_name: string; reason: string }[];
  }>("/trading/queue", true);
  const [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const items =
    strategies.data?.items.filter(
      (s) => s.performance.deployment && s.status !== "ARCHIVED",
    ) || [];
  async function pause(s: Strategy) {
    setBusy(s.strategy_id);
    setError("");
    try {
      await api("/strategies/" + s.strategy_id + "/status", {
        method: "POST",
        body: JSON.stringify({ status: "PAUSED", expected_version: s.version }),
      });
      await strategies.load();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <Header
        title="Execution monitoring"
        text="Follow paper replay progress, pause execution and resolve approvals. Status refreshes every 15 seconds."
      />
      <ErrorNotice error={error || strategies.error || queue.error} />
      <section className="panel editor">
        <h2>Awaiting your decision</h2>
        {queue.data?.items.length ? (
          queue.data.items.map((i) => (
            <Link
              className="alert-row"
              key={i.intent_id}
              to={"/trading/intents/" + i.intent_id}
            >
              <strong>{i.strategy_name}</strong>
              <span>{i.reason.replaceAll("_", " ")}</span>
              <span>Review trade →</span>
            </Link>
          ))
        ) : (
          <p>No paper trades are waiting for approval.</p>
        )}
      </section>
      <h2>Deployment status</h2>
      {items.length ? (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Deployment</th>
                <th>Replay progress</th>
                <th>State</th>
                <th>Verified fills</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.strategy_id}>
                  <td>{s.name}</td>
                  <td>
                    {s.performance.deployment!.step}/96 closed candles
                    <progress max={96} value={s.performance.deployment!.step} />
                  </td>
                  <td>
                    <Status
                      value={
                        s.performance.deployment!.step >= 96
                          ? "COMPLETED"
                          : s.status
                      }
                    />
                  </td>
                  <td>{s.performance.verified_trades}</td>
                  <td>
                    <div className="button-row">
                      <Link to={detail(s, "Trades & proofs")}>
                        Execution log →
                      </Link>
                      {s.performance.deployment!.step < 96 &&
                        ["LIVE", "DEGRADED"].includes(s.status) && (
                          <button
                            className="secondary"
                            disabled={busy === s.strategy_id}
                            onClick={() => void pause(s)}
                          >
                            Pause
                          </button>
                        )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        strategies.data && (
          <Empty text="Deploy a reviewed plan to track paper execution here." />
        )
      )}
    </>
  );
}

export function PerformancePage() {
  const { data, error } = useData<{ items: Strategy[] }>("/strategies");
  const items = data?.items.filter((s) => s.performance.deployment) || [];
  return (
    <>
      <Header
        title="Performance"
        text="Measured results from stored fills. Backtest and paper replay cover separate historical periods; neither is an exchange account return."
      />
      <ErrorNotice error={error} />
      {items.length ? (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Paper PnL</th>
                <th>Paper return</th>
                <th>Backtest return</th>
                <th>Drawdown</th>
                <th>Fees</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.strategy_id}>
                  <td>{s.name}</td>
                  <td>
                    {s.performance.verified_trades
                      ? amount(s.performance.live.pnl)
                      : "No fills"}
                  </td>
                  <td>{pct(s.performance.live_return)}</td>
                  <td>{pct(s.performance.backtest_return)}</td>
                  <td>{pct(s.performance.live.max_drawdown)}</td>
                  <td>{amount(s.performance.live.fees)}</td>
                  <td>
                    <Link to={detail(s, "Performance")}>
                      Accounting & periods →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        data && (
          <Empty text="Performance is calculated when a paper deployment records fills." />
        )
      )}
      <section className="panel editor">
        <h2>What these numbers mean</h2>
        <p>
          PnL includes configured fees and slippage. Drawdown measures
          peak-to-trough portfolio equity, including open positions. Empty
          histories display no result.
        </p>
        <Link to="/help">Calculation methodology →</Link>
      </section>
    </>
  );
}

export function GuardrailsPage() {
  const { data, error } = useData<{ items: Strategy[] }>("/strategies");
  return (
    <>
      <Header
        title="Guardrails"
        text="See exactly what every strategy may trade, how much it can risk and when a person must approve."
      />
      <ErrorNotice error={error} />
      {data?.items.length ? (
        <div className="strategy-grid">
          {data.items.map((s) => (
            <section className="panel editor" key={s.strategy_id}>
              <h2>{s.name}</h2>
              <p>
                {s.market} · version {s.version}
              </p>
              <dl className="builder-review">
                <div>
                  <dt>Position / trade</dt>
                  <dd>
                    {amount(s.guardrails.max_position_size)} /{" "}
                    {amount(s.guardrails.max_trade_size)}
                  </dd>
                </div>
                <div>
                  <dt>Loss thresholds</dt>
                  <dd>
                    {s.guardrails.max_daily_loss}% daily ·{" "}
                    {s.guardrails.max_drawdown}% drawdown
                  </dd>
                </div>
                <div>
                  <dt>Human review</dt>
                  <dd>Above {amount(s.guardrails.human_approval_above)}</dd>
                </div>
                <div>
                  <dt>Permissions</dt>
                  <dd>{s.guardrails.allowed_markets.join(", ")} · spot only</dd>
                </div>
              </dl>
              <Link to={detail(s, "Guardrails")}>
                Inspect policy & rejection checks →
              </Link>
            </section>
          ))}
        </div>
      ) : (
        data && (
          <Empty text="Define permissions before you create your first agent." />
        )
      )}
      <section className="panel editor">
        <h2>Operator integrations</h2>
        <p>
          Loss thresholds block new buys. Open positions can continue to lose
          value. External connectors require operator configuration.
        </p>
        <div className="button-row">
          <Link to="/control/resources">Configured resources</Link>
          <Link to="/control/integrations">SDK & MCP documentation</Link>
          <Link to="/control/approvals">Connector approvals</Link>
        </div>
      </section>
    </>
  );
}

type TestResult = {
  test_id: string;
  strategy_id: string;
  strategy_name: string;
  strategy_version: number;
  started_at: number;
  dataset: string;
  metrics: { return_pct: number; max_drawdown: number; trade_count: number };
  market_data?: { provider: string; period_start: number; period_end: number };
};
export function TestsPage() {
  const { data, error } = useData<{ items: TestResult[] }>("/strategy-tests");
  return (
    <>
      <Header
        title="Backtest results"
        text="Actual completed test runs, their exchange-data periods and measured results. Select a run to inspect its strategy version."
      />
      <ErrorNotice error={error} />
      {data?.items.length ? (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Test / strategy</th>
                <th>Source period</th>
                <th>Return</th>
                <th>Drawdown</th>
                <th>Trades</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((t) => (
                <tr key={t.test_id}>
                  <td>
                    {t.strategy_name} · v{t.strategy_version}
                    <small className="section-subtext">
                      {new Date(t.started_at * 1000).toLocaleString()}
                    </small>
                  </td>
                  <td>
                    {t.market_data?.provider || "Legacy test"}
                    <small className="section-subtext">
                      {t.market_data &&
                        new Date(
                          t.market_data.period_start * 1000,
                        ).toLocaleDateString() +
                          " — " +
                          new Date(
                            t.market_data.period_end * 1000,
                          ).toLocaleDateString()}
                    </small>
                  </td>
                  <td>{pct(t.metrics.return_pct)}</td>
                  <td>{pct(t.metrics.max_drawdown)}</td>
                  <td>{t.metrics.trade_count}</td>
                  <td>
                    <Link
                      to={
                        "/strategies/" +
                        t.strategy_id +
                        "?tab=Tests&version=" +
                        t.strategy_version
                      }
                    >
                      Inspect test →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        data && (
          <Empty text="Run and review a historical test in Create agent. Completed strategy tests are collected here." />
        )
      )}
    </>
  );
}

export function AgentRoster() {
  const { agents } = useApp();
  const recipes = useData<{ items: Strategy[] }>("/strategies");
  return (
    <>
      <Header
        title="My agent instances"
        text="Your personal executors: each has a trading recipe, its own limits, identity and private execution history."
      >
        <Link className="primary" to="/">
          Choose an agent
        </Link>
      </Header>
      {agents.length ? (
        <div className="strategy-grid">
          {agents.map((a) => (
            <section className="panel editor" key={a.agent_id}>
              <Status value={a.active ? "ACTIVE" : "STOPPED"} />
              <h2>{a.name}</h2>
              <p>{a.description}</p>
              <code className="section-id">{a.agent_id}</code>
              <Link to={"/agents/" + a.agent_id}>Identity & access →</Link>
            </section>
          ))}
        </div>
      ) : (
        <Empty text="Describe the job and review its limits to create an agent." />
      )}
    </>
  );
}

export function AgentIdentityPage() {
  const { id } = useParams(),
    { refresh } = useApp();
  const agent = useData<Agent>("/agents/" + id),
    strategies = useData<{ items: Strategy[] }>("/strategies");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function toggle() {
    if (!agent.data) return;
    setBusy(true);
    try {
      await api("/agents/" + id + "/status", {
        method: "POST",
        body: JSON.stringify({ active: !agent.data.active }),
      });
      await agent.load();
      await refresh();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Header
        title={agent.data?.name || "Agent identity"}
        text="Identity and execution access. Strategy versions and risk policies are managed separately."
      />
      <ErrorNotice error={error || agent.error || strategies.error} />
      {agent.data && (
        <>
          <section className="panel editor">
            <Status value={agent.data.active ? "ACTIVE" : "STOPPED"} />
            <h2>Declared intent</h2>
            <p>{agent.data.description}</p>
            <h3>Signing identity</h3>
            <code className="section-id">{agent.data.public_key}</code>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void toggle()}
            >
              {agent.data.active ? "Stop agent" : "Enable agent"}
            </button>
            <p>
              Stopping blocks new actions and invalidates pending approvals.
              Existing evidence stays available.
            </p>
          </section>
          <h2>Assigned strategies</h2>
          <div className="strategy-grid">
            {strategies.data?.items
              .filter((s) => s.agent_id === id)
              .map((s) => (
                <Link
                  className="strategy-card"
                  key={s.strategy_id}
                  to={detail(s, "Versions")}
                >
                  <h3>{s.name}</h3>
                  <p>
                    v{s.version} · {s.market} · {s.status}
                  </p>
                  <span>Open configuration →</span>
                </Link>
              ))}
          </div>
        </>
      )}
    </>
  );
}

export function DeveloperStudio() {
  const { data, error } = useData<{ items: Strategy[] }>("/strategies");
  const items = data?.items || [];
  return (
    <>
      <Header
        title="Developer studio"
        text="Evaluate, publish and improve trading agents. Give every strategy version a track record that others can inspect."
      >
        <Link className="primary" to="/agents/new">
          Prepare an agent for publication →
        </Link>
      </Header>
      <div className="market-paths">
        <section className="panel editor">
          <h2>Guardrails → evaluate → publish → improve</h2>
          <p>
            Describe your strategy, review guardrails and run historical tests.
            Create a private paper runner, record its executions, then publish
            its identity, version and evidence. Publication is a separate
            reviewed action.
          </p>
          <p>
            Current execution supports mean reversion, momentum and
            buy-and-hold. Custom external AI model execution is not supported by
            this runner.
          </p>
          <Link to="/help/publication">
            Publication and evidence requirements →
          </Link>
        </section>
        <section className="panel editor">
          <h2>Your publication pipeline</h2>
          {data ? (
            <>
              <p>
                {items.filter((s) => s.listed).length} published ·{" "}
                {items.filter((s) => !s.listed).length} private
              </p>
              <p>
                {items.filter((s) => s.performance.verified_trades > 0).length}{" "}
                with verified paper fills ·{" "}
                {items.filter((s) => s.performance.backtest != null).length}{" "}
                with a backtest baseline
              </p>
            </>
          ) : (
            <p>Loading your records…</p>
          )}
          <Link to="/leaderboard">Inspect leaderboard conditions →</Link>
        </section>
      </div>
      <ErrorNotice error={error} />
      <h2>Your agents and publication evidence</h2>
      {data && !items.length && (
        <section className="panel editor">
          <h3>No agent prepared yet</h3>
          <p>
            Start with a supported strategy and run its tests. A new agent
            remains private until you review its public disclosure.
          </p>
          <Link to="/agents/new">Prepare your first agent →</Link>
        </section>
      )}
      {!!items.length && (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Agent / strategy</th>
                <th>Evidence</th>
                <th>Evaluate & improve</th>
                <th>Publication</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.strategy_id}>
                  <td>
                    <strong>{s.agent_name}</strong>
                    <small className="section-subtext">
                      {s.name} · v{s.version} · {s.market}
                    </small>
                  </td>
                  <td>
                    {s.performance.backtest
                      ? "Backtest recorded"
                      : "No backtest yet"}
                    <small className="section-subtext">
                      {s.performance.verified_trades} verified paper fills ·{" "}
                      {s.performance.live.closed_trade_count} closed trades
                    </small>
                    <small className="section-subtext">
                      Replay {s.performance.deployment?.step ?? 0}/96
                    </small>
                  </td>
                  <td>
                    <Link to={detail(s, "Guardrails")}>Review guardrails</Link>
                    <small className="section-subtext">
                      <Link to={detail(s, "Tests")}>Run evaluations →</Link>
                    </small>
                    <small className="section-subtext">
                      <Link to={detail(s, "Versions")}>
                        Improve strategy version →
                      </Link>
                    </small>
                    <small className="section-subtext">
                      <Link to={detail(s, "Performance")}>
                        Inspect performance →
                      </Link>
                    </small>
                  </td>
                  <td>
                    <Link to={"/strategies/" + s.strategy_id + "?publish=1"}>
                      {s.listed ? "Manage publication" : "Publish agent"}
                    </Link>
                    {s.listed && (
                      <small className="section-subtext">
                        <Link to={"/exchange/strategies/" + s.strategy_id}>
                          View public evidence →
                        </Link>
                      </small>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
