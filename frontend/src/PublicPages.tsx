import React, { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  CheckCheck,
  ShieldCheck,
  Search,
  Star,
  ArrowDownToLine,
  ExternalLink,
  Scale,
} from "lucide-react";
import {
  api,
  ApiError,
  Checks,
  Config,
  download,
  Receipt,
  setCsrf,
  short,
  verifyLocally,
} from "./api";

export type Metrics = {
  counts: Record<string, number>;
  total: number;
  verified_lamports: number;
  settled: number;
  success_rate: number | null;
  reliability_score: number | null;
  sample_label: string;
  median_resolution_seconds: number | null;
  last_action_at: number | null;
};
export type PublicAgent = {
  offer: null | { kind: string; version: number; runtime: string };
  agent_id: string;
  name: string;
  description: string;
  tagline: string;
  category: string;
  active: boolean;
  public_key: string;
  created_at: number;
  metrics: Metrics;
};
export const amount = (n: number) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: 9 }).format(n);
export const when = (n: number | null) =>
  n ? new Date(n * 1000).toLocaleString() : "No activity yet";
export const err = (e: unknown) => (e instanceof Error ? e.message : String(e));
export function ErrorNotice({ error }: { error: string }) {
  return error ? (
    <div className="error" role="alert">
      {error}
    </div>
  ) : null;
}
export function Status({ value }: { value: string }) {
  return <span className={"badge " + value.toLowerCase()}>{value}</span>;
}
export function PublicShell({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    void api<{ csrf_token: string }>("/auth/me")
      .then((r) => setCsrf(r.csrf_token))
      .catch(() => {});
  }, []);
  return (
    <div className="public-shell">
      <header className="public-nav">
        <Link to="/explore" className="brand">
          <span className="brand-mark">
            <CheckCheck size={22} />
          </span>
          tracy<span className="brand-dot">.</span>
        </Link>
        <nav>
          <Link to="/explore">Explore agents</Link>
          <Link to="/methodology">How proof works</Link>
          <Link className="primary" to="/">
            My workspace <ArrowRight size={15} />
          </Link>
        </nav>
      </header>
      <main className="public-main">{children}</main>
      <footer className="public-footer">
        <span>Tracy / Proof of Action</span>
        <span>
          Solana Devnet · Test funds · Records published by their owners
        </span>
        <Link to="/methodology">Verification & methodology</Link>
      </footer>
    </div>
  );
}
function MetricTiles({ m }: { m: Metrics }) {
  return (
    <div className="metric-tiles">
      <div>
        <span>Verified actions</span>
        <strong>{m.counts.VERIFIED}</strong>
      </div>
      <div>
        <span>Execution success</span>
        <strong>{m.success_rate === null ? "—" : m.success_rate + "%"}</strong>
        <small>{m.settled} settled attempts</small>
      </div>
      <div>
        <span>Reliability lower bound</span>
        <strong>
          {m.reliability_score === null ? "—" : m.reliability_score + "%"}
        </strong>
        <small>{m.sample_label}</small>
      </div>
      <div>
        <span>Verified volume</span>
        <strong>{amount(m.verified_lamports / 1e9)}</strong>
        <small>Test SOL</small>
      </div>
    </div>
  );
}
export function AgentTile({
  agent,
  selected,
  onSelect,
}: {
  agent: PublicAgent;
  selected?: boolean;
  onSelect?: () => void;
}) {
  return (
    <article className="panel public-agent-card">
      <div className="agent-card-head">
        <span className="agent-avatar">
          <Bot />
        </span>
        <span className="category-tag">{agent.category}</span>
      </div>
      <h2>
        <Link to={"/a/" + agent.agent_id}>{agent.name}</Link>
      </h2>
      <p>
        {agent.tagline ||
          agent.description ||
          "A signed identity with a public action history."}
      </p>
      <div className="public-card-metrics">
        <div>
          <strong>{agent.metrics.counts.VERIFIED}</strong>
          <span>verified actions</span>
        </div>
        <div>
          <strong>
            {agent.metrics.reliability_score === null
              ? "—"
              : agent.metrics.reliability_score + "%"}
          </strong>
          <span>reliability lower bound</span>
        </div>
      </div>
      <small>
        {agent.metrics.sample_label} · {agent.active ? "Active" : "Stopped"}
      </small>
      <div className="agent-card-actions">
        {agent.offer && (
          <Link className="primary" to={"/install/" + agent.agent_id}>
            Use agent
          </Link>
        )}
        <Link className="secondary" to={"/a/" + agent.agent_id}>
          View evidence <ArrowRight size={14} />
        </Link>
        {onSelect && (
          <button
            className={"secondary " + (selected ? "selected" : "")}
            onClick={onSelect}
            aria-pressed={selected}
          >
            <Scale size={14} />
            {selected ? "Selected" : "Compare"}
          </button>
        )}
      </div>
    </article>
  );
}
export function Explore() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<{
      items: PublicAgent[];
      total: number;
    } | null>(null),
    [error, setError] = useState(""),
    [selected, setSelected] = useState<string[]>([]);
  const q = params.get("q") || "",
    sort = params.get("sort") || "recent",
    category = params.get("category") || "",
    page = Math.max(0, Number(params.get("page")) || 0);
  const update = (key: string, value: string) => {
    const p = new URLSearchParams(params);
    p.set(key, value);
    p.delete("page");
    setParams(p);
  };
  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(() => {
      setError("");
      void api<typeof data>(
        "/public/agents?" +
          new URLSearchParams({
            q,
            sort,
            category,
            limit: "12",
            offset: String(page * 12),
          }),
        { signal: abort.signal },
      )
        .then(setData)
        .catch((e) => {
          if (e.name !== "AbortError") setError(err(e));
        });
    }, 200);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [q, sort, category, page]);
  return (
    <>
      <section className="catalog-hero">
        <div>
          <div className="eyebrow">THE EVIDENCE IS THE PROFILE</div>
          <h1>
            Meet agents.
            <br />
            Inspect their actions.
          </h1>
          <p>
            Inspect an agent's history, choose Use agent, then set your own
            recipients and limits. Run your private copy on Solana Devnet and
            follow every verified result.
          </p>
          <div className="button-row">
            <Link className="primary" to="/installed">
              My installed agents <ArrowRight size={16} />
            </Link>
            <Link className="secondary" to="/agents/new">
              Connect your agent <ArrowRight size={16} />
            </Link>
            <Link className="secondary" to="/methodology">
              How Tracy verifies
            </Link>
          </div>
        </div>
        <div className="catalog-proof-art" aria-hidden="true">
          <div className="proof-orbit">
            <ShieldCheck size={66} />
          </div>
          <div className="proof-label">SIGNED INTENT → ON-CHAIN EVIDENCE</div>
          <div className="proof-label muted">
            Identity · Policy · Execution · Receipt
          </div>
        </div>
      </section>
      <div className="catalog-heading">
        <div>
          <div className="eyebrow">PUBLIC DIRECTORY</div>
          <h2>Agents with a record.</h2>
        </div>
        <span>{data?.total ?? "…"} published agents</span>
      </div>
      <div className="catalog-controls">
        <label className="search-control">
          <Search size={17} />
          <input
            aria-label="Search public agents"
            placeholder="Search by name or purpose"
            value={q}
            onChange={(e) => update("q", e.target.value)}
          />
        </label>
        <select
          aria-label="Agent category"
          value={category}
          onChange={(e) => update("category", e.target.value)}
        >
          <option value="">All categories</option>
          {["payouts", "automation", "research", "other"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
        <select
          aria-label="Sort agents"
          value={sort}
          onChange={(e) => update("sort", e.target.value)}
        >
          <option value="recent">Recently published</option>
          <option value="verified">Most verified actions</option>
          <option value="reliability">Reliability lower bound</option>
        </select>
      </div>
      <ErrorNotice error={error} />
      {data ? (
        <>
          {data.items.length ? (
            <div className="agent-cards public-grid">
              {data.items.map((a) => (
                <AgentTile
                  key={a.agent_id}
                  agent={a}
                  selected={selected.includes(a.agent_id)}
                  onSelect={() =>
                    setSelected((s) =>
                      s.includes(a.agent_id)
                        ? s.filter((i) => i !== a.agent_id)
                        : s.length < 3
                          ? [...s, a.agent_id]
                          : s,
                    )
                  }
                />
              ))}
            </div>
          ) : (
            <div className="panel empty">
              <Bot size={36} />
              <h3>No agents found</h3>
              <p>
                {q || category
                  ? "Try a different search or category."
                  : "Publish an agent from its workspace settings to start the directory."}
              </p>
              <Link to="/agents" className="primary">
                Open workspace
              </Link>
            </div>
          )}
          <Pager
            page={page}
            total={data.total}
            size={12}
            setPage={(n) => {
              const p = new URLSearchParams(params);
              p.set("page", String(n));
              setParams(p);
            }}
          />
        </>
      ) : (
        !error && <div className="empty">Loading public records…</div>
      )}
      {selected.length > 0 && (
        <div className="compare-tray">
          <span>{selected.length} of 3 agents selected</span>
          <Link className="primary" to={"/compare?ids=" + selected.join(",")}>
            Compare evidence <Scale size={16} />
          </Link>
          <button onClick={() => setSelected([])}>Clear</button>
        </div>
      )}
      <p className="methodology-note">
        Metrics describe recorded Devnet execution, not intelligence,
        profitability or an endorsement. Scores require at least 5 settled
        attempts. <Link to="/methodology">Read the methodology →</Link>
      </p>
    </>
  );
}
export function PublicProfile() {
  const { id } = useParams();
  const [agent, setAgent] = useState<PublicAgent | null>(null),
    [items, setItems] = useState<Receipt[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(0),
    [filter, setFilter] = useState(""),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false),
    [notice, setNotice] = useState("");
  useEffect(() => {
    setAgent(null);
    setPage(0);
    void api<PublicAgent>("/public/agents/" + id)
      .then(setAgent)
      .catch((e) => setError(err(e)));
    void api<{ items: PublicAgent[] }>("/favorites")
      .then((r) => setSaved(r.items.some((a) => a.agent_id === id)))
      .catch(() => {});
  }, [id]);
  useEffect(() => {
    setError("");
    void api<{ items: Receipt[]; total: number }>(
      "/public/agents/" +
        id +
        "/receipts?" +
        new URLSearchParams({
          limit: "20",
          offset: String(page * 20),
          status: filter,
        }),
    )
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
      })
      .catch((e) => setError(err(e)));
  }, [id, page, filter]);
  async function favorite() {
    try {
      await api("/favorites/" + id, { method: saved ? "DELETE" : "PUT" });
      setSaved(!saved);
      setNotice("");
    } catch (e) {
      setNotice(
        e instanceof ApiError && e.status === 401
          ? "Sign in to save this agent to your watchlist."
          : err(e),
      );
    }
  }
  return (
    <>
      <Link className="breadcrumb" to="/explore">
        ← Explore agents
      </Link>
      <ErrorNotice error={error} />
      {agent && (
        <>
          <section className="public-profile-heading">
            <div>
              <div className="eyebrow">
                {agent.category.toUpperCase()} / SOLANA DEVNET
              </div>
              <h1>{agent.name}</h1>
              <p>{agent.tagline || agent.description}</p>
              <span className="badge">
                {agent.active ? "Active" : "Stopped"}
              </span>
            </div>
            <div className="button-row">
              {agent.offer && (
                <Link className="primary" to={"/install/" + agent.agent_id}>
                  Use agent
                </Link>
              )}
              <button className="secondary" onClick={() => void favorite()}>
                <Star size={16} />
                {saved ? "Saved to watchlist" : "Save agent"}
              </button>
              <Link className="primary" to={"/compare?ids=" + id}>
                Compare <Scale size={16} />
              </Link>
            </div>
          </section>
          {notice && (
            <div className="notice">
              {notice} <Link to="/">Open workspace</Link>
            </div>
          )}
          <section className="panel editor">
            <h2>{agent.offer ? "Ready to install" : "Evidence profile"}</h2>
            <p>
              {agent.offer
                ? agent.offer.kind === "scheduled_payout"
                  ? "Scheduled payouts: send a configured list at a fixed interval, for a bounded number of cycles."
                  : "Batch payouts: send a configured list once, in order, stopping on a refusal or failure."
                : "This author shares transaction evidence. A runnable offer has not been enabled."}
            </p>
            {agent.offer && (
              <p>
                Free Devnet recipe hosted by Tracy, version{" "}
                {agent.offer.version}. Choose your own recipients and limits.
                Your copy gets a separate key and private history. These metrics
                describe this published identity, not the performance of your
                future copy.
              </p>
            )}
          </section>
          <MetricTiles m={agent.metrics} />
          <div className="profile-details">
            <section className="panel editor">
              <h2>About this agent</h2>
              <p>
                {agent.description || "The owner has not added a description."}
              </p>
              <small className="muted">
                Description supplied by the owner. Supported action:
                solana.transfer.
              </small>
              <div>
                <span className="small-label">PUBLIC SIGNING KEY</span>
                <code className="break-word">{agent.public_key}</code>
              </div>
            </section>
            <section className="panel editor">
              <h2>Complete published history</h2>
              <p>
                {agent.metrics.counts.REJECTED} policy refusals ·{" "}
                {agent.metrics.counts.FAILED} failures ·{" "}
                {agent.metrics.counts.PENDING + agent.metrics.counts.PREPARING}{" "}
                pending
              </p>
              <p className="muted">
                All past and future receipts are published together. Policy
                refusals do not improve or reduce the reliability score.
              </p>
              <Link to="/methodology" className="text-button">
                Understand these metrics →
              </Link>
            </section>
          </div>
          <section className="panel">
            <div className="panel-heading">
              <h2>Signed action receipts</h2>
              <select
                aria-label="Public receipt status"
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value);
                  setPage(0);
                }}
              >
                <option value="">All outcomes</option>
                {["VERIFIED", "REJECTED", "FAILED"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Sequence</th>
                    <th>Outcome</th>
                    <th>Transfer</th>
                    <th>Time</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((r) => (
                    <tr key={r.receipt_id}>
                      <td>#{r.sequence}</td>
                      <td>
                        <Status value={r.status} />
                        <small className="table-reason">
                          {r.reason.replaceAll("_", " ")}
                        </small>
                      </td>
                      <td>
                        {amount(r.requested.amount)} SOL
                        <small className="table-reason">
                          {short(r.requested.to, 7)}
                        </small>
                      </td>
                      <td>{when(r.timestamp)}</td>
                      <td>
                        <Link
                          className="text-button"
                          to={"/public/receipts/" + r.receipt_id}
                        >
                          Inspect proof <ArrowRight size={14} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!items.length && (
              <div className="empty">No receipts for this filter.</div>
            )}
            <Pager page={page} total={total} size={20} setPage={setPage} />
          </section>
        </>
      )}
    </>
  );
}
export function Pager({
  page,
  total,
  size,
  setPage,
}: {
  page: number;
  total: number;
  size: number;
  setPage: (n: number) => void;
}) {
  return (
    <div className="pagination">
      <button disabled={page === 0} onClick={() => setPage(page - 1)}>
        Previous
      </button>
      <span>
        {total === 0
          ? "No records"
          : page * size +
            1 +
            "–" +
            Math.min((page + 1) * size, total) +
            " of " +
            total}
      </span>
      <button
        disabled={(page + 1) * size >= total}
        onClick={() => setPage(page + 1)}
      >
        Next
      </button>
    </div>
  );
}
export function Compare() {
  const [params] = useSearchParams();
  const ids = [
    ...new Set((params.get("ids") || "").split(",").filter(Boolean)),
  ].slice(0, 3);
  const [agents, setAgents] = useState<PublicAgent[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    setError("");
    setAgents([]);
    void Promise.all(
      ids.map((id) =>
        api<PublicAgent>("/public/agents/" + encodeURIComponent(id)),
      ),
    )
      .then(setAgents)
      .catch((e) => setError(err(e)));
  }, [params.toString()]);
  const rows: [string, (a: PublicAgent) => React.ReactNode][] = [
    ["Category", (a) => a.category],
    ["Verified actions", (a) => a.metrics.counts.VERIFIED],
    ["Failed attempts", (a) => a.metrics.counts.FAILED],
    ["Policy refusals", (a) => a.metrics.counts.REJECTED],
    ["Pending", (a) => a.metrics.counts.PENDING + a.metrics.counts.PREPARING],
    [
      "Execution success",
      (a) =>
        a.metrics.success_rate === null
          ? "No settled attempts"
          : a.metrics.success_rate + "%",
    ],
    [
      "Reliability lower bound",
      (a) =>
        a.metrics.reliability_score === null
          ? "Insufficient history"
          : a.metrics.reliability_score + "%",
    ],
    ["Sample size", (a) => a.metrics.settled + " settled attempts"],
    ["Verified test SOL", (a) => amount(a.metrics.verified_lamports / 1e9)],
    [
      "Median resolution",
      (a) =>
        a.metrics.median_resolution_seconds === null
          ? "—"
          : a.metrics.median_resolution_seconds + " seconds",
    ],
    ["Last action", (a) => when(a.metrics.last_action_at)],
  ];
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">COMPARE THE RECORD</div>
          <h1>Evidence, side by side.</h1>
          <p>The same measurements and definitions for every agent.</p>
        </div>
        <Link className="secondary" to="/explore">
          Choose agents
        </Link>
      </div>
      <ErrorNotice error={error} />
      {agents.length ? (
        <section className="panel compare-table table-scroll">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                {agents.map((a) => (
                  <th key={a.agent_id}>
                    <Link to={"/a/" + a.agent_id}>{a.name} ↗</Link>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, fn]) => (
                <tr key={label}>
                  <td>{label}</td>
                  {agents.map((a) => (
                    <td key={a.agent_id}>{fn(a)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        !error && (
          <div className="panel empty">
            Select up to three agents in Explore to compare their records.
          </div>
        )
      )}
      <p className="methodology-note">
        Small samples are explicitly marked. Activity volume alone does not
        determine reliability.{" "}
        <Link to="/methodology">Calculation details →</Link>
      </p>
    </>
  );
}
export function PublicProof({ shared = false }: { shared?: boolean }) {
  const { id } = useParams();
  const base = shared ? "/public/proofs/" : "/public/receipts/";
  const [receipt, setReceipt] = useState<Receipt | null>(null),
    [config, setConfig] = useState<Config | null>(null),
    [checks, setChecks] = useState<Checks | null>(null),
    [local, setLocal] = useState<boolean | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [checkedAt, setCheckedAt] = useState<number | null>(null);
  useEffect(() => {
    setError("");
    setReceipt(null);
    setChecks(null);
    setLocal(null);
    void Promise.all([api<Receipt>(base + id), api<Config>("/config")])
      .then(([r, c]) => {
        setReceipt(r);
        setConfig(c);
      })
      .catch((e) => setError(err(e)));
  }, [base, id]);
  async function verify() {
    if (!receipt || !config) return;
    setBusy(true);
    setError("");
    try {
      const [r, l] = await Promise.all([
        api<Checks>(base + id + "/verify"),
        verifyLocally(receipt, config.poa_public_key),
      ]);
      setChecks(r);
      setLocal(l);
      setCheckedAt(Date.now() / 1000);
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <ErrorNotice error={error} />
      {receipt ? (
        <>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {shared ? "SHARED PROOF" : "PUBLIC PROOF"} / SOLANA DEVNET
              </div>
              <h1>A record you can verify.</h1>
              <p className="mono">{receipt.receipt_id}</p>
            </div>
            <button
              className="secondary"
              onClick={() => download(receipt, receipt.receipt_id + ".json")}
            >
              <ArrowDownToLine size={16} /> Export JSON
            </button>
          </div>
          <section className="panel proof-summary">
            <Status value={receipt.status} />
            <h2>{amount(receipt.requested.amount)} SOL</h2>
            <p>{receipt.reason.replaceAll("_", " ")}</p>
            <dl>
              <div>
                <dt>Agent</dt>
                <dd>{receipt.agent_name}</dd>
              </div>
              <div>
                <dt>Recipient</dt>
                <dd className="mono break-word">{receipt.requested.to}</dd>
              </div>
              <div>
                <dt>Recorded</dt>
                <dd>{when(receipt.timestamp)}</dd>
              </div>
              <div>
                <dt>Policy</dt>
                <dd>
                  {receipt.policy.approved ? "Allowed" : "Rejected"} · Version{" "}
                  {receipt.policy.version || "legacy"}
                </dd>
              </div>
              <div>
                <dt>Sequence</dt>
                <dd>#{receipt.sequence}</dd>
              </div>
              <div>
                <dt>Transaction</dt>
                <dd>
                  {receipt.result.tx_signature ? (
                    <a
                      target="_blank"
                      rel="noreferrer"
                      href={
                        "https://explorer.solana.com/tx/" +
                        receipt.result.tx_signature +
                        "?cluster=devnet"
                      }
                    >
                      Open Solana Explorer <ExternalLink size={13} />
                    </a>
                  ) : (
                    "No transaction submitted"
                  )}
                </dd>
              </div>
            </dl>
          </section>
          <section className="panel editor">
            <h2>
              <ShieldCheck size={20} /> Verify this proof
            </h2>
            <p className="form-help">
              The browser checks the signature and hash. Tracy checks the agent
              signature, full receipt chain and fresh RPC evidence. Gateway
              public key: <code>{config?.poa_public_key}</code>
            </p>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void verify()}
            >
              {busy ? "Checking evidence…" : "Verify public proof"}
            </button>
            {checks && (
              <div className="check-results">
                {[
                  ["Browser signature and hash", local],
                  ["Agent signature", checks.request_signature_valid],
                  ["Chain", checks.chain_valid],
                  ["Fresh evidence", checks.evidence_valid],
                ].map(([label, ok]) => (
                  <div key={String(label)}>
                    <span>{label}</span>
                    <b className={ok === true ? "green" : "muted"}>
                      {ok === true
                        ? "Valid"
                        : ok === false
                          ? "Failed"
                          : "Unavailable"}
                    </b>
                  </div>
                ))}
                <p
                  className={
                    checks.valid && local ? "verification-success" : "notice"
                  }
                >
                  {checks.valid && local
                    ? receipt.status === "REJECTED"
                      ? "Valid signed refusal. No transfer was executed."
                      : "Verified against fresh blockchain evidence."
                    : "Successful execution is not currently proven. Inspect the outcome and evidence."}
                </p>
                <small>
                  Checked {when(checkedAt)} ·{" "}
                  {checks.evidence_status.replaceAll("_", " ")}
                </small>
              </div>
            )}
          </section>
          <section className="panel editor">
            <h2>Signed contents</h2>
            <details>
              <summary>Inspect canonical receipt fields</summary>
              <pre>{JSON.stringify(receipt, null, 2)}</pre>
            </details>
            {shared ? (
              <p className="form-help">
                This link exposes only this receipt. Previous receipts are not
                disclosed by the link; chain verification above is performed by
                the gateway.
              </p>
            ) : (
              <button
                className="secondary"
                onClick={async () => {
                  try {
                    download(
                      await api(base + id + "/chain"),
                      receipt.receipt_id + "-chain.json",
                    );
                  } catch (e) {
                    setError(err(e));
                  }
                }}
              >
                Export full chain
              </button>
            )}
          </section>
        </>
      ) : (
        !error && <div className="empty">Loading proof…</div>
      )}
    </>
  );
}
export function Methodology() {
  return (
    <article className="methodology panel editor">
      <div className="eyebrow">WHAT TRACY PROVES</div>
      <h1>Read the evidence.</h1>
      <p>
        An agent signs its intent with Ed25519. Tracy applies spending limits,
        sends a Devnet transaction and independently reads Solana RPC to check
        what happened. A signed receipt binds the intent, policy and observed
        result.
      </p>
      <h2>Outcomes have different meanings</h2>
      <p>
        <b>VERIFIED</b>: the exact transfer was confirmed. <b>REJECTED</b>: the
        policy blocked it before execution. <b>FAILED</b>: preparation,
        submission or evidence failed. <b>PENDING</b>: the result remains
        unresolved and its budget is reserved.
      </p>
      <h2>A transparent reliability measure</h2>
      <p>
        Execution success = VERIFIED ÷ (VERIFIED + FAILED). Policy refusals and
        pending requests are displayed separately. Reliability is the lower
        bound of the two-sided 95% Wilson confidence interval for that success
        rate. It is shown only after 5 settled attempts. The sample size always
        accompanies the score.
      </p>
      <pre>
        n = verified + failed{"\n"}p = verified / n{"\n"}z = 1.96{"\n"}lower =
        (p + z²/(2n) - z × sqrt(p(1-p)/n + z²/(4n²))) / (1 + z²/n)
      </pre>
      <p>
        These are recorded execution outcomes, not a measure of intelligence or
        future performance. Owners can generate trivial test activity, so volume
        and scores must not be treated as endorsements. An owner publishes an
        agent's complete receipt history, not a selected set of wins.
      </p>
      <p>
        <a
          href="https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm"
          target="_blank"
          rel="noreferrer"
        >
          Statistical reference: NIST confidence intervals for proportions
        </a>
      </p>
      <h2>Independent checks and their limits</h2>
      <p>
        Receipt signatures and hashes can be checked offline using an
        independently obtained Tracy public key. Chain links detect edits or
        gaps against a known chain head. Live verification also depends on the
        RPC provider and uses confirmed commitment. A gateway attestation is not
        a trustless proof, and a chain alone cannot reveal a hidden tail.
      </p>
      <h2>Publication and privacy</h2>
      <p>
        Agents begin private. Publishing makes their profile and all past and
        future receipts public, including addresses, amounts, historic policy
        snapshots and signed requests. Individual proof links reveal only the
        selected full receipt and expire. Revoking access cannot remove copies
        already downloaded or public blockchain records.
      </p>
      <h2>Devnet funds and control</h2>
      <p>
        Tracy executes solana.transfer on Solana Devnet using a shared sponsor
        wallet. Per-agent policies, account quotas and a platform-wide daily cap
        constrain spending. No real-money purchase or mainnet execution is
        supported. Stopping an agent prevents new dispatches; already submitted
        transactions can still settle.
      </p>
      <Link className="primary" to="/explore">
        Explore public evidence <ArrowRight size={16} />
      </Link>
    </article>
  );
}
