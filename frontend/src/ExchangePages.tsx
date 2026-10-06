import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCheck } from "lucide-react";
import { api } from "./api";
import { StrategyCard, type Strategy } from "./LifecyclePages";
import { ErrorNotice, err } from "./PublicPages";
import { HelpLink } from "./Copilot";
import "./exchange.css";

function useListings() {
  const [items, setItems] = useState<Strategy[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api<{ items: Strategy[] }>("/public/trading/strategies")
      .then((r) => {
        if (active) setItems(r.items);
      })
      .catch((e) => {
        if (active) setError(err(e));
      });
    return () => {
      active = false;
    };
  }, []);
  return { items, error };
}
const percent = (n: number | null | undefined) =>
  n == null ? "—" : n.toFixed(2) + "%";
const dates = (s: Strategy) => {
  const source = s.performance.replay_market_data;
  return source
    ? new Date(source.period_start * 1000)
        .toISOString()
        .slice(0, 16)
        .replace("T", " ") +
        " → " +
        new Date(source.period_end * 1000)
          .toISOString()
          .slice(0, 16)
          .replace("T", " ") +
        " UTC"
    : "No recorded replay window";
};
// A rank only compares completed observations over the same market window and cost model.
export function benchmarkKey(s: Strategy) {
  const source = s.performance.replay_market_data;
  if (!source) return "";
  return JSON.stringify([
    source.provider,
    s.market,
    s.timeframe,
    source.period_start,
    source.period_end,
    s.starting_capital,
    s.strategy_config.fee_bps,
    s.strategy_config.slippage_bps,
  ]);
}
export function rankEligible(s: Strategy) {
  const p = s.performance;
  return Boolean(
    benchmarkKey(s) &&
    p.deployment?.step === 96 &&
    p.live.closed_trade_count >= 5 &&
    p.verified_trades > 0 &&
    p.verified_trades === p.live.trade_count &&
    p.live_return != null,
  );
}
function EvidenceNote() {
  return (
    <div className="paper-note">
      <CheckCheck size={16} />
      <span>
        Current evidence: historical backtests and signed paper fills on
        recorded Binance candles. Verification establishes recorded execution
        and data integrity; it does not establish live exchange performance or
        AI capability. <HelpLink topic="proofs">What is verified?</HelpLink>
      </span>
    </div>
  );
}
export function TradingExchange() {
  const { items, error } = useListings();
  const [query, setQuery] = useState("");
  const [market, setMarket] = useState("");
  const [evidence, setEvidence] = useState("");
  const visible = items?.filter(
    (s) =>
      (!market || s.market === market) &&
      (!evidence ||
        (evidence === "fills"
          ? s.performance.verified_trades > 0
          : rankEligible(s))) &&
      (s.agent_name + " " + s.name + " " + s.strategy_config.runner)
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <>
      <section className="exchange-hero">
        <div className="eyebrow">TRACY / ADAPTIVE TRADING AGENTS</div>
        <h1>
          Your strategy is the baseline.
          <br />
          Your agent learns.
        </h1>
        <p>
          Turn supported trading rules into agents that learn from their outcomes.
          Compare each change with the original strategy, then publish the rules
          or a complete learned Bundle. Start with virtual capital in the Devnet lab.
        </p>
        <div className="button-row">
          <Link className="primary" to="/lab">Build and train <ArrowRight size={16} /></Link>
          <Link className="secondary" to="/bundles">Explore Bundles</Link>
          <Link className="secondary" to="/leaderboard">
            View leaderboard
          </Link>
        </div>
        <div className="exchange-orbit" aria-hidden="true">
          <CheckCheck size={64} />
          <span>BUILD → TRAIN → PROVE → PUBLISH</span>
        </div>
      </section>
      <EvidenceNote />
      <section id="agents" className="marketplace-listings">
        <div className="section-heading">
          <div>
            <div className="eyebrow">PUBLIC AGENTS / VERSIONED STRATEGIES</div>
            <h2>Agent marketplace</h2>
          </div>
          <Link to="/compare">Compare side by side →</Link>
        </div>
        <div className="market-filters">
          <label>
            Search agents
            <input
              value={query}
              placeholder="Agent, strategy or execution template"
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label>
            Market
            <select
              aria-label="Market"
              value={market}
              onChange={(e) => setMarket(e.target.value)}
            >
              <option value="">All markets</option>
              {["SOL/USDC", "BTC/USDC", "ETH/USDC"].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <label>
            Evidence
            <select
              aria-label="Evidence"
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
            >
              <option value="">All published agents</option>
              <option value="fills">With verified paper fills</option>
              <option value="ranked">Eligible for a leaderboard</option>
            </select>
          </label>
        </div>
        <ErrorNotice error={error} />
        {!items && !error && <p role="status">Loading published agents…</p>}
        {items && (
          <p className="muted">
            {visible?.length} matching listings · latest {items.length}{" "}
            publications, up to 100. Each listing identifies an agent and its
            current strategy version.
          </p>
        )}
        <div className="strategy-grid">
          {visible?.map((s) => (
            <StrategyCard key={s.strategy_id} s={s} publicView />
          ))}
        </div>
        {items && !visible?.length && (
          <section className="panel editor">
            <h2>
              {items.length
                ? "No agents match these filters"
                : "The marketplace is waiting for its first published agent"}
            </h2>
            <p>
              {items.length
                ? "Try another market or evidence filter."
                : "Listings appear when developers explicitly publish their agents. There are no sample agents or invented returns."}
            </p>
            {items.length ? (
              <button
                className="secondary"
                onClick={() => {
                  setQuery("");
                  setMarket("");
                  setEvidence("");
                }}
              >
                Reset filters
              </button>
            ) : (
              <Link to="/developers">Open developer studio →</Link>
            )}
          </section>
        )}
      </section>
      <div className="market-paths">
        <section className="panel editor">
          <div className="eyebrow">FOR USERS</div>
          <h2>Find an agent worth testing</h2>
          <p>
            Inspect the track record and its source period. Compare agents, then
            test a personal copy with your own capital and limits. Your history
            starts with your own executions.
          </p>
          <Link to="/help/start">How choosing an agent works →</Link>
        </section>
        <section className="panel editor">
          <div className="eyebrow">FOR DEVELOPERS</div>
          <h2>Build a track record others can inspect</h2>
          <p>
            Evaluate your strategy, record paper executions and publish an agent
            with its evidence. Improve it through versioned tests and compare
            its results under matching conditions.
          </p>
          <Link to="/developers">Open developer studio →</Link>
        </section>
      </div>
      <p className="muted">
        MVP execution uses the displayed mean-reversion, momentum or
        buy-and-hold template. Arbitrary external AI models are not executed by
        this paper runner.
      </p>
    </>
  );
}
export function TradingLeaderboard() {
  const { items, error } = useListings();
  const [cohort, setCohort] = useState("");
  const [metric, setMetric] = useState("return");
  const groups = new Map<string, Strategy>();
  items?.filter(rankEligible).forEach((s) => groups.set(benchmarkKey(s), s));
  const ranked = (items || [])
    .filter((s) => rankEligible(s) && benchmarkKey(s) === cohort)
    .sort(
      (a, b) =>
        (metric === "drawdown"
          ? a.performance.live.max_drawdown - b.performance.live.max_drawdown
          : b.performance.live_return! - a.performance.live_return!) ||
        a.strategy_id.localeCompare(b.strategy_id),
    );
  const value = (s: Strategy) =>
    metric === "drawdown"
      ? s.performance.live.max_drawdown
      : s.performance.live_return;
  const ranks = ranked.map(
    (s, i) =>
      1 +
      ranked.slice(0, i).filter((other) => value(other) !== value(s)).length,
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">PUBLIC PERFORMANCE / MATCHED CONDITIONS</div>
          <h1>Agent leaderboard</h1>
          <p>
            Rank completed paper runs within one market window and cost model.
          </p>
        </div>
        <HelpLink topic="leaderboard">Ranking methodology</HelpLink>
      </div>
      <EvidenceNote />
      <section className="panel editor">
        <h2>Choose comparison conditions</h2>
        <p>
          Eligibility: all 96 replay candles processed, at least 5 closed trades
          and every recorded fill verified. A group shares market, interval,
          recorded period, starting capital, fees and slippage. Strategy rules
          and risk limits may differ; inspect them before choosing an agent.
        </p>
        <div className="market-filters">
          <label>
            Benchmark group
            <select value={cohort} onChange={(e) => setCohort(e.target.value)}>
              <option value="">Select a recorded window</option>
              {[...groups].map(([key, s]) => (
                <option value={key} key={key}>
                  {s.market} · {s.timeframe} · {dates(s)} · {s.starting_capital}{" "}
                  USDC · fee {s.strategy_config.fee_bps} / slippage{" "}
                  {s.strategy_config.slippage_bps} bps
                </option>
              ))}
            </select>
          </label>
          <label>
            Rank by
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              <option value="return">Paper return · highest first</option>
              <option value="drawdown">Max drawdown · lowest first</option>
            </select>
          </label>
        </div>
      </section>
      <ErrorNotice error={error} />
      {!items && !error && <p>Loading public evidence…</p>}
      {ranked.length > 0 && (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Agent / strategy version</th>
                <th>Paper return</th>
                <th>Max drawdown</th>
                <th>Closed trades</th>
                <th>Verified fills</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((s, i) => (
                <tr key={s.strategy_id}>
                  <td>{ranks[i]}</td>
                  <td>
                    <Link to={"/a/" + s.agent_id}>{s.agent_name}</Link>
                    <small className="section-subtext">
                      {s.name} · v{s.version}
                    </small>
                  </td>
                  <td>{percent(s.performance.live_return)}</td>
                  <td>{percent(s.performance.live.max_drawdown)}</td>
                  <td>{s.performance.live.closed_trade_count}</td>
                  <td>{s.performance.verified_trades}</td>
                  <td>
                    <Link
                      to={
                        "/exchange/strategies/" +
                        s.strategy_id +
                        "?version=" +
                        s.version
                      }
                    >
                      Inspect run →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {items && !ranked.length && (
        <section className="panel editor">
          <h2>
            {groups.size
              ? "Select a group to see its ranking"
              : "No eligible public runs yet"}
          </h2>
          <p>
            {groups.size
              ? "Results from different periods are not assigned a shared rank."
              : "Published agents remain discoverable while their track records are incomplete. Ranks appear only after the eligibility checks above are met."}
          </p>
          <Link to="/">Browse published agents →</Link>
        </section>
      )}
      <p className="muted">
        {ranked.length === 1
          ? "Only one eligible listing in this group; this is not evidence of superiority. "
          : ""}
        Rankings use up to the 100 most recently updated public listings.
        Returns are cumulative historical observations. Publication is chosen by
        authors; this is not an independent competition or a profitability
        prediction.
      </p>
      {ranked.length > 1 && (
        <Link
          className="secondary"
          to={
            "/compare?ids=" +
            ranked
              .slice(0, 4)
              .map((s) => s.strategy_id)
              .join(",")
          }
        >
          Compare leading agents and their limits →
        </Link>
      )}
    </>
  );
}
