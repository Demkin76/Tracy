import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Bell,
  Download,
  Globe,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  Star,
} from "lucide-react";
import { Action, Agent, api, setCsrf, short } from "./api";
import { useApp } from "./app-context";
import {
  AgentTile,
  amount,
  err,
  ErrorNotice,
  Metrics,
  Pager,
  PublicAgent,
  Status,
  when,
} from "./PublicPages";

function useData<T>(url: string, interval = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState("");
  async function reload() {
    try {
      setData(await api<T>(url));
      setError("");
    } catch (e) {
      setError(err(e));
    }
  }
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const r = await api<T>(url);
        if (active) {
          setData(r);
          setError("");
        }
      } catch (e) {
        if (active) setError(err(e));
      }
    }
    void load();
    const timer = interval ? setInterval(() => void load(), interval) : null;
    return () => {
      active = false;
      if (timer) clearInterval(timer);
    };
  }, [url, interval]);
  return { data, error, reload };
}
function Heading({ title, text }: { title: string; text: string }) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">TRACY / WORKSPACE</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
    </div>
  );
}
export function PublicationPanel({
  agent,
  onSaved,
}: {
  agent: Agent;
  onSaved: () => Promise<void>;
}) {
  const [category, setCategory] = useState(agent.category || "payouts"),
    [tagline, setTagline] = useState(agent.tagline || ""),
    [consent, setConsent] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function save(listed: boolean) {
    setBusy(true);
    setError("");
    try {
      await api("/agents/" + agent.agent_id + "/publication", {
        method: "PUT",
        body: JSON.stringify({
          listed,
          category,
          tagline,
          disclose_history: consent,
        }),
      });
      setConsent(false);
      await onSaved();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel editor publication-panel">
      <h2>
        <Globe size={19} /> Public profile
      </h2>
      <ErrorNotice error={error} />
      <p className="form-help">
        {agent.listed
          ? "This agent is listed. Its complete receipt history is public."
          : "This agent is private. You decide when to publish it."}
      </p>
      <div className="form-columns">
        <label>
          Profile category
          <select
            aria-label="Profile category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {["payouts", "automation", "research", "other"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Short public introduction
          <input
            value={tagline}
            onChange={(e) => setTagline(e.target.value)}
            maxLength={160}
          />
        </label>
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
        />
        Publish this profile and all past and future receipts, including
        addresses, amounts, historic policies and signed requests.
      </label>
      <p className="form-help">
        Unpublishing blocks future directory access. Already downloaded copies
        and blockchain data cannot be recalled. Existing individual share links
        are managed separately.
      </p>
      <div className="button-row">
        <button
          className="primary"
          disabled={busy || !consent}
          onClick={() => void save(true)}
        >
          {agent.listed ? "Update public profile" : "Publish agent"}
        </button>
        {!!agent.listed && (
          <>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void save(false)}
            >
              Unpublish agent
            </button>
            <Link className="secondary" to={"/a/" + agent.agent_id}>
              View public profile <ArrowRight size={15} />
            </Link>
          </>
        )}
      </div>
    </section>
  );
}
export function SharePanel({ receiptId }: { receiptId: string }) {
  const [consent, setConsent] = useState(false),
    [days, setDays] = useState("7"),
    [url, setUrl] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function share() {
    setBusy(true);
    setError("");
    try {
      const r = await api<{ path: string }>("/shares", {
        method: "POST",
        body: JSON.stringify({
          receipt_id: receiptId,
          expires_days: Number(days),
          disclose_receipt: consent,
        }),
      });
      setUrl(location.origin + r.path);
      setConsent(false);
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel editor share-panel">
      <h2>
        <Globe size={18} /> Share this proof
      </h2>
      <ErrorNotice error={error} />
      <p className="form-help">
        Create a public link to this full receipt without publishing your other
        actions. Anyone with the link can inspect its addresses, amount, policy
        snapshot and signatures.
      </p>
      <label>
        Link lifetime
        <select
          aria-label="Link lifetime"
          value={days}
          onChange={(e) => setDays(e.target.value)}
        >
          <option value="1">1 day</option>
          <option value="7">7 days</option>
          <option value="30">30 days</option>
        </select>
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
        />
        I want to share this full receipt with anyone who has the link.
      </label>
      <button
        className="primary"
        disabled={!consent || busy}
        onClick={() => void share()}
      >
        Create proof link
      </button>
      {url && (
        <div className="notice">
          <a href={url} target="_blank" rel="noreferrer">
            {url}
          </a>
          <p>Manage and revoke links in Account & security.</p>
        </div>
      )}
    </section>
  );
}
type HistoryAction = Action & {
  agent_name: string;
  agent_id: string;
  request_id: string;
  last_checked_at: number | null;
  check_attempts: number;
};
export function ActivityPage() {
  const { agents } = useApp();
  const [params, setParams] = useSearchParams(),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  const page = Math.max(0, Number(params.get("page")) || 0),
    agent = params.get("agent") || "",
    status = params.get("status") || "",
    q = params.get("q") || "",
    from = params.get("from") || "",
    to = params.get("to") || "";
  const filters = new URLSearchParams({
    agent_id: agent,
    status,
    q,
    since: from ? String(Date.parse(from + "T00:00:00Z") / 1000) : "0",
    until: to ? String(Date.parse(to + "T23:59:59Z") / 1000) : "0",
  });
  const {
    data,
    error: loadError,
    reload,
  } = useData<{ items: HistoryAction[]; total: number }>(
    "/history?" + filters + "&limit=25&offset=" + page * 25,
    5000,
  );
  function change(k: string, v: string) {
    const p = new URLSearchParams(params);
    p.set(k, v);
    p.delete("page");
    setParams(p);
  }
  async function reconcile(id: string) {
    setBusy(id);
    setError("");
    try {
      await api("/actions/" + id + "/reconcile", { method: "POST" });
      await reload();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy("");
    }
  }
  async function csv() {
    setError("");
    try {
      const res = await fetch("/v1/history/export?" + filters, {
        credentials: "include",
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "tracy-history.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(err(e));
    }
  }
  return (
    <>
      <Heading
        title="Every action, accounted for."
        text="Filter your complete history. Pending confirmations refresh automatically."
      />
      <ErrorNotice error={error || loadError} />
      <div className="panel history-filters">
        <label>
          Agent
          <select
            aria-label="Agent"
            value={agent}
            onChange={(e) => change("agent", e.target.value)}
          >
            <option value="">All my agents</option>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            aria-label="Status"
            value={status}
            onChange={(e) => change("status", e.target.value)}
          >
            <option value="">All outcomes</option>
            {["VERIFIED", "REJECTED", "FAILED", "PENDING", "PREPARING"].map(
              (s) => (
                <option key={s}>{s}</option>
              ),
            )}
          </select>
        </label>
        <label>
          Search
          <input
            value={q}
            onChange={(e) => change("q", e.target.value)}
            placeholder="Request, recipient or transaction"
          />
        </label>
        <label>
          From (UTC)
          <input
            type="date"
            value={from}
            onChange={(e) => change("from", e.target.value)}
          />
        </label>
        <label>
          Through (UTC)
          <input
            type="date"
            value={to}
            onChange={(e) => change("to", e.target.value)}
          />
        </label>
        <button className="secondary" onClick={() => void csv()}>
          <Download size={15} /> Export CSV
        </button>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>{data?.total ?? "…"} matching actions</h2>
          <button className="text-button" onClick={() => void reload()}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Agent / request</th>
                <th>Outcome</th>
                <th>Transfer</th>
                <th>Time</th>
                <th>Proof</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((a) => (
                <tr key={a.action_id}>
                  <td>
                    <Link to={"/agents/" + a.agent_id}>{a.agent_name}</Link>
                    <small className="table-reason">{a.request_id}</small>
                  </td>
                  <td>
                    <Status value={a.status} />
                    <small className="table-reason">
                      {a.reason?.replaceAll("_", " ")}
                    </small>
                  </td>
                  <td>
                    {amount(a.request.params.amount)} SOL
                    <small className="table-reason">
                      {short(a.request.params.to, 6)}
                    </small>
                  </td>
                  <td>{when(a.created_at)}</td>
                  <td>
                    {a.receipt_id ? (
                      <Link
                        className="text-button"
                        to={"/receipts/" + a.receipt_id}
                      >
                        View proof <ArrowRight size={14} />
                      </Link>
                    ) : (
                      <button
                        className="text-button"
                        disabled={busy === a.action_id}
                        onClick={() => void reconcile(a.action_id)}
                      >
                        Check RPC
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && !data.items.length && (
          <div className="empty">No actions match these filters.</div>
        )}
        <Pager
          page={page}
          total={data?.total || 0}
          size={25}
          setPage={(n) => {
            const p = new URLSearchParams(params);
            p.set("page", String(n));
            setParams(p);
          }}
        />
      </section>
    </>
  );
}
type Analytics = Metrics & {
  daily: (Metrics & { day: string })[];
  days: number;
  agent_count: number;
};
export function AnalyticsPage() {
  const [days, setDays] = useState("30");
  const { data, error } = useData<Analytics>("/analytics?days=" + days, 10000);
  const runtime = useData<{
    reconciler_enabled: boolean;
    last_tick_at: number | null;
    pending_actions: number;
    last_error_at: number | null;
  }>("/runtime", 10000);
  const max = Math.max(1, ...(data?.daily.map((d) => d.total) || []));
  return (
    <>
      <Heading
        title="Understand your agents."
        text="Execution outcomes, spending and confirmation health across your workspace."
      />
      <div className="toolbar">
        <span>All times are UTC</span>
        <select
          aria-label="Analytics period"
          value={days}
          onChange={(e) => setDays(e.target.value)}
        >
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 90 days</option>
        </select>
      </div>
      <ErrorNotice error={error || runtime.error} />
      {data && (
        <>
          <div className="metric-tiles">
            <div>
              <span>Verified actions</span>
              <strong>{data.counts.VERIFIED}</strong>
              <small>{data.total} total requests</small>
            </div>
            <div>
              <span>Execution success</span>
              <strong>
                {data.success_rate === null ? "—" : data.success_rate + "%"}
              </strong>
              <small>{data.settled} settled attempts</small>
            </div>
            <div>
              <span>Verified volume</span>
              <strong>{amount(data.verified_lamports / 1e9)}</strong>
              <small>Test SOL</small>
            </div>
            <div>
              <span>Policy refusals</span>
              <strong>{data.counts.REJECTED}</strong>
              <small>Blocked before execution</small>
            </div>
          </div>
          <section className="panel editor">
            <h2>Daily activity</h2>
            <div
              className="activity-chart"
              role="img"
              aria-label={"Daily recorded actions for " + days + " days"}
            >
              {data.daily.map((d) => (
                <div
                  key={d.day}
                  className="chart-column"
                  title={
                    d.day +
                    ": " +
                    d.total +
                    " requests; " +
                    d.counts.VERIFIED +
                    " verified"
                  }
                >
                  <div
                    className="chart-bar"
                    style={{ height: Math.max(2, (d.total / max) * 150) }}
                  >
                    <div
                      className="chart-verified"
                      style={{
                        height:
                          (d.total ? (d.counts.VERIFIED / d.total) * 100 : 0) +
                          "%",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <div className="chart-axis">
              <span>{data.daily[0]?.day}</span>
              <span>Green: verified · Gray: other outcomes</span>
              <span>{data.daily.at(-1)?.day}</span>
            </div>
            <details>
              <summary>Read daily values</summary>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>UTC day</th>
                      <th>Total</th>
                      <th>Verified</th>
                      <th>Rejected</th>
                      <th>Failed</th>
                      <th>Test SOL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.daily.map((d) => (
                      <tr key={d.day}>
                        <td>{d.day}</td>
                        <td>{d.total}</td>
                        <td>{d.counts.VERIFIED}</td>
                        <td>{d.counts.REJECTED}</td>
                        <td>{d.counts.FAILED}</td>
                        <td>{amount(d.verified_lamports / 1e9)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </section>
          <div className="settings-grid">
            <section className="panel editor">
              <h2>Confirmation service</h2>
              <p>
                {runtime.data?.reconciler_enabled
                  ? "Automatic reconciliation is enabled."
                  : "Automatic reconciliation is disabled."}
              </p>
              <p>
                {runtime.data?.pending_actions ?? "…"} pending transactions ·
                Last cycle: {when(runtime.data?.last_tick_at || null)}
              </p>
              <p className="form-help">
                Only existing transaction signatures are checked. A timeout
                never triggers a fresh transfer. Old unresolved reservations
                remain in the budget.
              </p>
              <Link className="text-button" to="/activity?status=PENDING">
                Inspect pending actions →
              </Link>
            </section>
            <section className="panel editor">
              <h2>Recorded reliability</h2>
              <p>
                {data.reliability_score === null
                  ? "Not enough settled attempts to show a reliability score."
                  : data.reliability_score +
                    "% conservative reliability lower bound."}
              </p>
              <p className="form-help">
                The score accounts for sample size. Rejections and pending
                actions are excluded. Failures remain visible and count as
                unsuccessful attempts.
              </p>
              <Link className="text-button" to="/methodology">
                Methodology →
              </Link>
            </section>
          </div>
        </>
      )}
    </>
  );
}
export function WatchlistPage() {
  const { data, error, reload } = useData<{ items: PublicAgent[] }>(
    "/favorites",
    15000,
  );
  const [failure, setFailure] = useState("");
  return (
    <>
      <Heading
        title="Your watchlist."
        text="Follow the public records you want to revisit."
      />
      <ErrorNotice error={error || failure} />
      {data?.items.length ? (
        <div className="agent-cards">
          {data.items.map((a) => (
            <div key={a.agent_id}>
              <AgentTile agent={a} />
              <button
                className="text-button"
                onClick={async () => {
                  try {
                    await api("/favorites/" + a.agent_id, { method: "DELETE" });
                    await reload();
                  } catch (e) {
                    setFailure(err(e));
                  }
                }}
              >
                Remove from watchlist
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="panel empty">
          <Star size={34} />
          <h3>No saved public agents</h3>
          <p>Agents that their owners unpublish no longer appear here.</p>
          <Link className="primary" to="/explore">
            Explore agents
          </Link>
        </div>
      )}
    </>
  );
}
export function NotificationsPage() {
  const { data, error, reload } = useData<{
    items: {
      receipt_id: string;
      agent_name: string;
      status: string;
      reason: string;
      completed_at: number;
      is_read: boolean;
    }[];
    unread: number;
  }>("/notifications", 5000);
  const [failure, setFailure] = useState("");
  return (
    <>
      <Heading
        title="Updates from your agents."
        text="New outcomes arrive automatically as transactions settle."
      />
      <ErrorNotice error={error || failure} />
      <div className="toolbar">
        <span>{data?.unread || 0} unread updates</span>
        <button
          className="secondary"
          onClick={async () => {
            try {
              await api("/notifications/read", { method: "POST" });
              await reload();
            } catch (e) {
              setFailure(err(e));
            }
          }}
        >
          Mark all as read
        </button>
      </div>
      <section className="panel notification-list">
        {data?.items.map((n) => (
          <Link
            className={"notification-item " + (n.is_read ? "" : "unread")}
            to={"/receipts/" + n.receipt_id}
            key={n.receipt_id}
          >
            <Bell size={18} />
            <div>
              <strong>{n.agent_name}</strong>
              <p>{n.reason.replaceAll("_", " ")}</p>
              <small>{when(n.completed_at)}</small>
            </div>
            <Status value={n.status} />
            <ArrowRight size={15} />
          </Link>
        ))}
        {data && !data.items.length && (
          <div className="empty">
            Your agents' first completed actions will appear here.
          </div>
        )}
      </section>
    </>
  );
}
export function FundingPage() {
  const { data, error, reload } = useData<{
    day: string;
    used_lamports: number;
    limit_lamports: number;
    remaining_lamports: number;
    execution_wallet: string;
    balance_lamports: number | null;
    rpc_available: boolean;
  }>("/funding", 15000);
  return (
    <>
      <Heading
        title="Devnet funding."
        text="A shared test-fund sponsor, with enforced limits for every workspace."
      />
      <ErrorNotice error={error} />
      {data && (
        <>
          <div className="metric-tiles">
            <div>
              <span>Workspace daily allowance</span>
              <strong>{amount(data.limit_lamports / 1e9)}</strong>
              <small>Test SOL</small>
            </div>
            <div>
              <span>Used / reserved</span>
              <strong>{amount(data.used_lamports / 1e9)}</strong>
              <small>Across all your agents</small>
            </div>
            <div>
              <span>Available today</span>
              <strong>{amount(data.remaining_lamports / 1e9)}</strong>
              <small>Day: {data.day} UTC</small>
            </div>
            <div>
              <span>Sponsor wallet balance</span>
              <strong>
                {data.balance_lamports === null
                  ? "—"
                  : amount(data.balance_lamports / 1e9)}
              </strong>
              <small>
                {data.rpc_available ? "Live Devnet RPC" : "RPC unavailable"}
              </small>
            </div>
          </div>
          <section className="panel editor">
            <h2>Execution wallet</h2>
            <code className="break-word">{data.execution_wallet}</code>
            <p>
              Transfers are signed by this Devnet sponsor wallet after your
              agent's intent passes its policy, account allowance and the
              platform daily cap. This is not your agent's signing key.
            </p>
            <div className="button-row">
              <a
                className="primary"
                target="_blank"
                rel="noreferrer"
                href="https://faucet.solana.com/"
              >
                Get test SOL from the faucet
              </a>
              <a
                className="secondary"
                target="_blank"
                rel="noreferrer"
                href={
                  "https://explorer.solana.com/address/" +
                  data.execution_wallet +
                  "?cluster=devnet"
                }
              >
                View execution wallet
              </a>
              <button className="secondary" onClick={() => void reload()}>
                <RefreshCw size={14} /> Refresh balance
              </button>
            </div>
            <p className="form-help">
              Fund only with Devnet SOL. Faucet availability is external. A
              platform-wide cap may block new transfers even when your personal
              allowance remains. Fees are paid by the sponsor and do not count
              toward your transfer budget.
            </p>
          </section>
        </>
      )}
    </>
  );
}
export function SecurityPage() {
  const { user, updateUser } = useApp();
  const [name, setName] = useState(user.name),
    [current, setCurrent] = useState(""),
    [password, setPassword] = useState(""),
    [recoveryPassword, setRecoveryPassword] = useState(""),
    [code, setCode] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const shares = useData<{
    items: {
      share_id: string;
      receipt_id: string;
      expires_at: number;
      revoked_at: number | null;
    }[];
  }>("/shares");
  const events = useData<{
    items: {
      event_id: number;
      kind: string;
      target: string;
      created_at: number;
    }[];
  }>("/account/events");
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      await events.reload();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Account & security."
        text="Manage your identity, recovery access and published proof links."
      />
      <ErrorNotice error={error || shares.error || events.error} />
      {notice && <div className="verification-success">{notice}</div>}
      <div className="settings-grid">
        <form
          className="panel editor"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              const u = await api<typeof user>("/account/profile", {
                method: "PATCH",
                body: JSON.stringify({ name }),
              });
              updateUser(u);
              setNotice("Profile saved.");
            });
          }}
        >
          <h2>Workspace identity</h2>
          <label>
            Account name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
            />
          </label>
          <label>
            Email
            <input readOnly value={user.email} />
          </label>
          <p className="form-help">
            Email is your sign-in identifier. Recovery uses a one-time code; no
            email delivery service is required.
          </p>
          <button className="primary" disabled={busy}>
            Save account name
          </button>
        </form>
        <form
          className="panel editor"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              const r = await api<{ recovery_code: string }>(
                "/account/recovery-code",
                {
                  method: "POST",
                  body: JSON.stringify({ current_password: recoveryPassword }),
                },
              );
              setCode(r.recovery_code);
              setRecoveryPassword("");
            });
          }}
        >
          <h2>
            <KeyRound size={18} /> Recovery code
          </h2>
          <p className="form-help">
            Generate a one-time recovery code and store it privately. Generating
            a new one invalidates the old code. Only a hash is stored by Tracy.
          </p>
          <label>
            Password to issue recovery code
            <input
              type="password"
              value={recoveryPassword}
              onChange={(e) => setRecoveryPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button className="secondary" disabled={busy}>
            Generate recovery code
          </button>
          {code && (
            <div className="issued-key">
              <label>
                Save this recovery code
                <input readOnly value={code} />
              </label>
              <p className="form-help">
                Shown only in this session. Keep it outside this browser.
              </p>
            </div>
          )}
        </form>
      </div>
      <form
        className="panel editor security-password"
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await api("/account/password", {
              method: "POST",
              body: JSON.stringify({
                current_password: current,
                new_password: password,
              }),
            });
            setCsrf(null);
            window.location.assign("/");
          });
        }}
      >
        <h2>Change password</h2>
        <div className="form-columns">
          <label>
            Current password
            <input
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            New password
            <input
              type="password"
              minLength={12}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
        </div>
        <p className="form-help">
          Changing or recovering your password revokes every session and
          personal API key. Sign in again and issue new API keys. Agent signing
          keys remain separate; use Stop agent to disable their execution.
        </p>
        <button className="secondary" disabled={busy}>
          Change password & sign out everywhere
        </button>
      </form>
      <section className="panel editor">
        <h2>Shared proof links</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Proof</th>
                <th>Expires</th>
                <th>Access</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shares.data?.items.map((s) => (
                <tr key={s.share_id}>
                  <td>
                    <Link to={"/receipts/" + s.receipt_id}>
                      {short(s.receipt_id, 8)}
                    </Link>
                  </td>
                  <td>{when(s.expires_at)}</td>
                  <td>
                    {s.revoked_at ? (
                      "Revoked"
                    ) : s.expires_at < Date.now() / 1000 ? (
                      "Expired"
                    ) : (
                      <Link to={"/proof/" + s.share_id} target="_blank">
                        Open shared link ↗
                      </Link>
                    )}
                  </td>
                  <td>
                    {!s.revoked_at && (
                      <button
                        className="text-button"
                        onClick={() =>
                          void run(async () => {
                            await api("/shares/" + s.share_id, {
                              method: "DELETE",
                            });
                            await shares.reload();
                          })
                        }
                      >
                        Revoke link
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!shares.data?.items.length && (
          <p className="form-help">
            Open a receipt to create a scoped, expiring link.
          </p>
        )}
      </section>
      <section className="panel editor">
        <h2>Security activity</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Event</th>
                <th>Target</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {events.data?.items.map((e) => (
                <tr key={e.event_id}>
                  <td>{e.kind.replaceAll("_", " ")}</td>
                  <td className="mono">{short(e.target, 10)}</td>
                  <td>{when(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
export function RecoveryPage() {
  const [email, setEmail] = useState(""),
    [code, setCode] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [done, setDone] = useState(false),
    [busy, setBusy] = useState(false);
  return (
    <div className="recovery-wrap">
      <form
        className="panel editor"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api("/auth/recover", {
              method: "POST",
              body: JSON.stringify({
                email,
                recovery_code: code,
                new_password: password,
              }),
            });
            setDone(true);
            setCode("");
            setPassword("");
            setCsrf(null);
          } catch (e) {
            setError(err(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        <h1>Recover your workspace.</h1>
        <ErrorNotice error={error} />
        {done ? (
          <>
            <div className="verification-success">
              Password reset. Previous sessions and API keys were revoked.
            </div>
            <Link className="primary" to="/">
              Sign in
            </Link>
          </>
        ) : (
          <>
            <p className="form-help">
              Use the one-time code you saved in Account & security. No reset is
              possible without a valid code.
            </p>
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
            <label>
              Recovery code
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="off"
                required
              />
            </label>
            <label>
              New password
              <input
                type="password"
                minLength={12}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
              />
            </label>
            <button className="primary" disabled={busy}>
              Reset password
            </button>
            <Link className="text-button" to="/">
              Back to sign in
            </Link>
          </>
        )}
      </form>
    </div>
  );
}
