import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, Agent } from "./api";
import { useApp } from "./app-context";
import {
  amount,
  err,
  ErrorNotice,
  PublicAgent,
  Status,
  when,
} from "./PublicPages";

type Transfer = { to: string; amount: number };
type Plan = {
  transfers: Transfer[];
  interval_seconds: number;
  max_cycles: number;
};
type InstallationData = {
  agent_id: string;
  source_agent_id: string;
  source_name: string;
  kind: string;
  offer_version: number;
  plan: Plan;
  revision: number;
  running: boolean;
  next_run_at: number | null;
  cycles: number;
  agent: Agent;
};
type Run = {
  run_id: string;
  status: string;
  reason: string;
  created_at: number;
  plan: Plan;
  actions: {
    action_id: string;
    status: string;
    reason: string | null;
    receipt_id: string | null;
  }[];
};
const initialPlan = (): Plan => ({
  transfers: [{ to: "", amount: 0.000001 }],
  interval_seconds: 3600,
  max_cycles: 1,
});
const kindName = (kind: string) =>
  kind === "scheduled_payout" ? "Scheduled payouts" : "Batch payouts";
export function GettingStarted() {
  return (
    <section className="panel editor journey">
      <div className="eyebrow">START HERE / DEVNET</div>
      <h2>Choose an agent. Set your rules. Follow its work.</h2>
      <p>
        Pick a ready-to-run payout agent from the catalog. Tracy creates your
        private copy with your recipients, limits and run history.
      </p>
      <ol>
        <li>
          <Link to="/explore">Explore agents</Link> and inspect their evidence.
        </li>
        <li>
          Choose <strong>Use agent</strong>, then configure your payouts.
        </li>
        <li>
          Open <Link to="/installed">Installed agents</Link> to run, schedule or
          stop.
        </li>
      </ol>
      <p className="muted">
        Activity shows transactions; Analytics summarizes results; Notifications
        reports outcomes. Connect SDK and Create agent are for authors bringing
        their own bots.
      </p>
    </section>
  );
}
function PlanFields({
  value,
  onChange,
  kind,
}: {
  value: Plan;
  onChange: (p: Plan) => void;
  kind: string;
}) {
  return (
    <div className="payout-fields">
      <h3>Payout instructions</h3>
      <p>
        Each row is a real Devnet transfer. Rows execute in order; a refusal or
        failure stops the rest of this run.
      </p>
      {value.transfers.map((t, i) => (
        <div className="payout-row" key={i}>
          <label>
            Recipient {i + 1}
            <input
              required
              aria-label={"Recipient " + (i + 1)}
              value={t.to}
              placeholder="Solana Devnet address"
              onChange={(e) =>
                onChange({
                  ...value,
                  transfers: value.transfers.map((v, j) =>
                    j === i ? { ...v, to: e.target.value.trim() } : v,
                  ),
                })
              }
            />
          </label>
          <label>
            Amount {i + 1} (SOL)
            <input
              required
              type="number"
              min="0.000000001"
              step="0.000000001"
              value={t.amount}
              onChange={(e) =>
                onChange({
                  ...value,
                  transfers: value.transfers.map((v, j) =>
                    j === i ? { ...v, amount: Number(e.target.value) } : v,
                  ),
                })
              }
            />
          </label>
          {value.transfers.length > 1 && (
            <button
              type="button"
              className="secondary"
              aria-label={"Remove payout " + (i + 1)}
              onClick={() =>
                onChange({
                  ...value,
                  transfers: value.transfers.filter((_, j) => i !== j),
                })
              }
            >
              Remove
            </button>
          )}
        </div>
      ))}
      <button
        type="button"
        className="secondary"
        disabled={value.transfers.length >= 20}
        onClick={() =>
          onChange({
            ...value,
            transfers: [...value.transfers, { to: "", amount: 0.000001 }],
          })
        }
      >
        Add payout
      </button>
      {kind === "scheduled_payout" && (
        <div className="payout-row">
          <label>
            Interval (minutes)
            <input
              required
              type="number"
              min="1"
              max="43200"
              step="1"
              value={value.interval_seconds / 60}
              onChange={(e) =>
                onChange({
                  ...value,
                  interval_seconds: Number(e.target.value) * 60,
                })
              }
            />
          </label>
          <label>
            Number of cycles
            <input
              required
              type="number"
              min="1"
              max="100"
              step="1"
              value={value.max_cycles}
              onChange={(e) =>
                onChange({ ...value, max_cycles: Number(e.target.value) })
              }
            />
          </label>
        </div>
      )}
      <div className="notice">
        One cycle: {amount(value.transfers.reduce((n, t) => n + t.amount, 0))}{" "}
        test SOL.
        {kind === "scheduled_payout" && (
          <>
            {" "}
            Schedule: up to {value.max_cycles} cycles,{" "}
            {amount(
              value.transfers.reduce((n, t) => n + t.amount, 0) *
                value.max_cycles,
            )}{" "}
            test SOL total. The first cycle starts immediately. Missed cycles
            are not replayed in a burst.
          </>
        )}{" "}
        Fees are paid separately by the platform. Your daily limit always
        applies.
      </div>
    </div>
  );
}
export function InstallAgent() {
  const { id } = useParams(),
    navigate = useNavigate(),
    { refresh } = useApp();
  const [source, setSource] = useState<PublicAgent | null>(null),
    [name, setName] = useState(""),
    [plan, setPlan] = useState<Plan>(initialPlan),
    [limit, setLimit] = useState("0.001"),
    [daily, setDaily] = useState("0.01"),
    [allowed, setAllowed] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [accepted, setAccepted] = useState(false);
  const attempt = useRef({ body: "", request_id: "" });
  useEffect(() => {
    void api<PublicAgent>("/public/agents/" + id)
      .then((a) => {
        setSource(a);
        setName("My " + a.name);
      })
      .catch((e) => setError(err(e)));
  }, [id]);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!source?.offer) return;
    setBusy(true);
    setError("");
    const body = {
      source_agent_id: id,
      expected_version: source.offer.version,
      name,
      plan,
      policy: {
        allowed_actions: ["solana.transfer"],
        max_transfer_sol: Number(limit),
        daily_budget_sol: Number(daily),
        allowed_recipients: allowed.trim()
          ? allowed.split(/[\s,]+/).filter(Boolean)
          : [...new Set(plan.transfers.map((t) => t.to))],
      },
    };
    const serialized = JSON.stringify(body);
    if (attempt.current.body !== serialized)
      attempt.current = { body: serialized, request_id: crypto.randomUUID() };
    try {
      const result = await api<InstallationData>("/installations", {
        method: "POST",
        body: JSON.stringify({
          ...body,
          request_id: attempt.current.request_id,
        }),
      });
      await refresh();
      navigate("/installed/" + result.agent_id);
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Link to={"/a/" + id} className="breadcrumb">
        ← Back to agent evidence
      </Link>
      <h1>Make this agent yours</h1>
      <ErrorNotice error={error} />
      {!source && !error && <p>Loading agent…</p>}
      {source && !source.offer && (
        <div className="notice">
          This profile currently shares evidence only. Its author has not
          enabled a runnable offer.{" "}
          <Link to="/explore">Choose another agent</Link>
        </div>
      )}
      {source?.offer && (
        <form className="panel editor install-form" onSubmit={submit}>
          <div className="eyebrow">
            {kindName(source.offer.kind)} / VERSION {source.offer.version}
          </div>
          <h2>{source.name}</h2>
          <p>
            Creates a separate private instance. Its history starts empty; the
            author's transactions remain on the original profile. This runs
            Tracy's documented payout recipe, not arbitrary code supplied by the
            author.
          </p>
          <label>
            Your instance name
            <input
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <PlanFields
            value={plan}
            onChange={setPlan}
            kind={source.offer.kind}
          />
          <h3>Your limits</h3>
          <div className="payout-row">
            <label>
              Maximum per transfer (SOL)
              <input
                required
                type="number"
                min="0.000000001"
                step="0.000000001"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
            </label>
            <label>
              Daily budget (SOL, UTC)
              <input
                required
                type="number"
                min="0.000000001"
                step="0.000000001"
                value={daily}
                onChange={(e) => setDaily(e.target.value)}
              />
            </label>
          </div>
          <label>
            Additional recipient control
            <textarea
              aria-label="Allowed payout recipients"
              value={allowed}
              placeholder="Leave empty to allow only the recipients above, or enter your explicit allowlist."
              onChange={(e) => setAllowed(e.target.value)}
            />
          </label>
          <label className="consent">
            <input
              type="checkbox"
              required
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            I reviewed this plan. Tracy will sign and run it on its server using
            shared test funds and my limits.
          </label>
          <p className="muted">
            Free Devnet execution. No wallet deposit required. Installing does
            not start any transfers. The author's later edits cannot change your
            saved plan. Keep your recovery code to retain account access.
          </p>
          <button className="primary" disabled={busy || !accepted}>
            {busy ? "Installing…" : "Install agent"}
          </button>
        </form>
      )}
    </>
  );
}
export function InstalledAgents() {
  const [items, setItems] = useState<InstallationData[] | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    void api<{ items: InstallationData[] }>("/installations")
      .then((r) => setItems(r.items))
      .catch((e) => setError(err(e)));
  }, []);
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR PRIVATE INSTANCES</div>
          <h1>Installed agents</h1>
          <p>
            Your settings, limits and execution history. Instances are separate
            from their authors.
          </p>
        </div>
        <Link to="/explore" className="primary">
          Choose an agent →
        </Link>
      </div>
      <ErrorNotice error={error} />
      {items === null && !error && <p>Loading installations…</p>}
      {items?.length === 0 && <GettingStarted />}
      <div className="catalog-grid">
        {items?.map((i) => (
          <article className="panel editor" key={i.agent_id}>
            <span className="category-tag">{kindName(i.kind)}</span>
            <h2>{i.agent.name}</h2>
            <p>
              From {i.source_name} · version {i.offer_version}
            </p>
            <p>
              {i.plan.transfers.length} payouts per cycle ·{" "}
              {amount(i.agent.budget.remaining_lamports / 1e9)} SOL remaining
              today
            </p>
            <Status
              value={
                !i.agent.active ? "STOPPED" : i.running ? "SCHEDULED" : "READY"
              }
            />
            <Link className="primary" to={"/installed/" + i.agent_id}>
              Open agent →
            </Link>
          </article>
        ))}
      </div>
    </>
  );
}
export function Installation() {
  const { id } = useParams(),
    { refresh } = useApp();
  const [data, setData] = useState<InstallationData | null>(null),
    [runs, setRuns] = useState<Run[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(0),
    [plan, setPlan] = useState<Plan>(initialPlan),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const revision = useRef(0),
    runRequest = useRef("");
  async function load() {
    const [i, r] = await Promise.all([
      api<InstallationData>("/installations/" + id),
      api<{ items: Run[]; total: number }>(
        "/installations/" + id + "/runs?limit=20&offset=" + page * 20,
      ),
    ]);
    setData(i);
    setRuns(r.items);
    setTotal(r.total);
    if (revision.current !== i.revision) {
      setPlan(i.plan);
      revision.current = i.revision;
    }
  }
  useEffect(() => {
    revision.current = 0;
    setData(null);
    void load().catch((e) => setError(err(e)));
    const timer = setInterval(
      () => void load().catch((e) => setError(err(e))),
      5000,
    );
    return () => clearInterval(timer);
  }, [id, page]);
  async function act(path: string, body?: unknown, method = "POST") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(path, {
        method,
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      await load();
      await refresh();
      return true;
    } catch (e) {
      setError(err(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  const occupied = runs.some((r) =>
    ["QUEUED", "RUNNING", "WAITING"].includes(r.status),
  );
  return (
    <>
      <Link className="breadcrumb" to="/installed">
        ← Installed agents
      </Link>
      <ErrorNotice error={error} />
      {!data && !error && <p>Loading your agent…</p>}
      {data && (
        <>
          <div className="page-heading">
            <div>
              <div className="eyebrow">{kindName(data.kind)} / DEVNET</div>
              <h1>{data.agent.name}</h1>
              <p>
                Installed from{" "}
                <Link to={"/a/" + data.source_agent_id}>
                  {data.source_name}
                </Link>
                , version {data.offer_version}. Private history starts with your
                own runs.
              </p>
            </div>
            <Link className="secondary" to={"/agents/" + id}>
              Edit limits & profile
            </Link>
          </div>
          <section className="panel editor">
            <div className="toolbar">
              <Status
                value={
                  !data.agent.active
                    ? "STOPPED"
                    : data.running
                      ? "SCHEDULED"
                      : occupied
                        ? "WORKING"
                        : "READY"
                }
              />
              <span>
                {amount(data.agent.budget.remaining_lamports / 1e9)} SOL
                remaining today
              </span>
            </div>
            {data.running && (
              <p>
                Next cycle: {when(data.next_run_at)} · {data.cycles} /{" "}
                {data.plan.max_cycles} cycles dispatched
              </p>
            )}
            <p>
              Tracy keeps working when this tab closes. Stop prevents future
              dispatch; a transaction already sent may still settle.
            </p>
            <div className="button-row">
              <button
                className="primary"
                disabled={
                  busy || !data.agent.active || data.running || occupied
                }
                onClick={async () => {
                  if (!runRequest.current)
                    runRequest.current = crypto.randomUUID();
                  if (
                    await act("/installations/" + id + "/runs", {
                      request_id: runRequest.current,
                    })
                  ) {
                    runRequest.current = "";
                    setNotice(
                      "Run queued. The server will execute it and update the history below.",
                    );
                  }
                }}
              >
                Run once
              </button>
              {data.kind === "scheduled_payout" && (
                <button
                  className="secondary"
                  disabled={
                    busy || !data.agent.active || data.running || occupied
                  }
                  onClick={async () => {
                    if (await act("/installations/" + id + "/start"))
                      setNotice("Schedule started. First cycle is due now.");
                  }}
                >
                  Start schedule
                </button>
              )}
              {data.agent.active ? (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => void act("/installations/" + id + "/stop")}
                >
                  Stop agent
                </button>
              ) : (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    void act("/agents/" + id + "/status", { active: true })
                  }
                >
                  Resume agent
                </button>
              )}
            </div>
            {notice && (
              <div className="notice" role="status">
                {notice}
              </div>
            )}
            <p className="muted">
              Current limit: {amount(data.agent.policy.max_transfer_sol)} SOL
              per transfer; {amount(data.agent.policy.daily_budget_sol)} SOL per
              UTC day. <Link to="/funding">Check platform test funds</Link>.
              Resume only enables the agent; start a new run or schedule
              explicitly.
            </p>
          </section>
          <details className="panel editor">
            <summary>Edit payout instructions</summary>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (
                  await act(
                    "/installations/" + id + "/plan",
                    { expected_revision: data.revision, plan },
                    "PUT",
                  )
                )
                  setNotice("Payout instructions saved.");
              }}
            >
              <PlanFields value={plan} onChange={setPlan} kind={data.kind} />
              <button
                className="primary"
                disabled={busy || data.running || occupied}
              >
                Save payout plan
              </button>
              {(data.running || occupied) && (
                <p>Stop the agent before changing its instructions.</p>
              )}
            </form>
          </details>
          <section className="panel editor">
            <h2>Your run history</h2>
            {!runs.length && (
              <p>
                No runs yet. Review your instructions above, then choose Run
                once.
              </p>
            )}
            {runs.map((r) => (
              <article className="run-card" key={r.run_id}>
                <div className="toolbar">
                  <strong>{when(r.created_at)}</strong>
                  <Status value={r.status} />
                </div>
                <code className="break-word">{r.run_id}</code>
                <p>
                  {r.plan.transfers.length} planned payouts · {r.actions.length}{" "}
                  recorded actions
                </p>
                {r.reason && <p>{r.reason}</p>}
                {r.actions.map((a) => (
                  <div className="run-action" key={a.action_id}>
                    <Status value={a.status} />
                    <span>
                      {(a.reason || "Preparing transaction").replaceAll(
                        "_",
                        " ",
                      )}
                    </span>
                    {a.receipt_id ? (
                      <Link to={"/receipts/" + a.receipt_id}>
                        Inspect proof →
                      </Link>
                    ) : (
                      <span>Awaiting confirmation…</span>
                    )}
                  </div>
                ))}
                {["BLOCKED", "FAILED"].includes(r.status) && (
                  <p>
                    Automatic execution stopped. Review the outcome and limits
                    before starting a new run. A new run repeats the complete
                    plan, including earlier successful rows.
                  </p>
                )}
              </article>
            ))}
            <div className="button-row">
              <button
                className="secondary"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous runs
              </button>
              <span>{total} total runs</span>
              <button
                className="secondary"
                disabled={(page + 1) * 20 >= total}
                onClick={() => setPage((p) => p + 1)}
              >
                Next runs
              </button>
            </div>
          </section>
        </>
      )}
    </>
  );
}
export function OfferPanel({ agentId }: { agentId: string }) {
  const [kind, setKind] = useState("batch_payout"),
    [enabled, setEnabled] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    void api<{ offer: null | { kind: string; enabled: boolean } }>(
      "/agents/" + agentId + "/offer",
    )
      .then((r) => {
        if (r.offer) {
          setKind(r.offer.kind);
          setEnabled(r.offer.enabled);
        }
      })
      .catch((e) => setError(err(e)));
  }, [agentId]);
  return (
    <form
      className="panel editor"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        setNotice("");
        try {
          await api("/agents/" + agentId + "/offer", {
            method: "PUT",
            body: JSON.stringify({ kind, enabled }),
          });
          setNotice(
            "Offer saved. Public, active profiles can now be installed. Existing copies keep their version.",
          );
        } catch (e) {
          setError(err(e));
        } finally {
          setBusy(false);
        }
      }}
    >
      <h2>Offer a runnable agent</h2>
      <p>
        Let visitors install a private copy using a supported Tracy payout
        recipe. Describe this recipe accurately in your public profile. Your
        existing history belongs to this identity; it does not certify every
        future installation.
      </p>
      <label>
        Execution recipe
        <select
          aria-label="Execution recipe"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="batch_payout">
            Batch payouts — one ordered list per run
          </option>
          <option value="scheduled_payout">
            Scheduled payouts — bounded recurring cycles
          </option>
        </select>
      </label>
      <label className="consent">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        Allow users to install this recipe
      </label>
      <p className="muted">
        Requires a published, active profile. Customers choose their own
        recipients and limits. This publishes a managed recipe, not your private
        keys or external bot code.
      </p>
      <ErrorNotice error={error} />
      {notice && <p role="status">{notice}</p>}
      <button className="secondary" disabled={busy}>
        Save runnable offer
      </button>
    </form>
  );
}
