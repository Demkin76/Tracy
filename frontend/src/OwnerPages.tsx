import { BrandMark } from "./BrandMark";
import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  Check,
  Code2,
  KeyRound,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import {
  Action,
  Agent,
  api,
  base64,
  Config,
  setCsrf,
  short,
  signAction,
} from "./api";
import { useApp, User } from "./app-context";
import { PublicationPanel } from "./WorkspacePages";
import { OfferPanel } from "./MarketplacePages";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const fmt = (n: number) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: 9 }).format(n);
function ErrorBox({ text }: { text: string }) {
  return text ? (
    <div className="error" role="alert">
      {text}
    </div>
  ) : null;
}
function Heading({ title, text }: { title: string; text: string }) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">TRACY / YOUR WORKSPACE</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
    </div>
  );
}
export function AuthScreen({ onLogin }: { onLogin: (user: User) => void }) {
  const [registrationOpen, setRegistrationOpen] = useState(false);
  useEffect(() => {
    void api<{ signup_enabled: boolean }>("/config")
      .then((c) => setRegistrationOpen(c.signup_enabled))
      .catch(() => {});
  }, []);
  const [signup, setSignup] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api<{ user: User; csrf_token: string }>(
        signup ? "/auth/signup" : "/auth/login",
        {
          method: "POST",
          body: JSON.stringify({
            email,
            password,
            ...(signup ? { name } : {}),
          }),
        },
      );
      setCsrf(data.csrf_token);
      onLogin(data.user);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-shell">
      <section className="auth-story">
        <Link to="/" className="brand">
          <BrandMark />
          tracy<span className="brand-dot">.</span>
        </Link>
        <div>
          <div className="hero-tag">A RECORD YOU CAN VERIFY</div>
          <h1>
            Trading agents.
            <br />
            Verifiable results.
          </h1>
          <p>
            Compare public agents. Test a personal instance. Publish evidence
            others can inspect.
          </p>
          <div className="auth-benefits">
            <span>
              <ShieldCheck /> Enforced spending policies
            </span>
            <span>
              <KeyRound /> Requests signed by your agent
            </span>
            <span>
              <Check /> Signed execution evidence
            </span>
          </div>
        </div>
        <small>Recorded market data · Paper execution</small>
      </section>
      <section className="auth-form">
        <div className="eyebrow">WELCOME TO TRACY</div>
        <h1>{signup ? "Create your workspace." : "Welcome back."}</h1>
        <p>
          {signup
            ? "Test agents from the marketplace or develop and publish your own."
            : "Sign in to manage your agents and proofs."}
        </p>
        <ErrorBox text={error} />
        <form onSubmit={submit}>
          {signup && (
            <label>
              Your name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={100}
                autoComplete="name"
              />
            </label>
          )}
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              maxLength={254}
              autoComplete="username"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={12}
              maxLength={128}
              required
              autoComplete={signup ? "new-password" : "current-password"}
            />
          </label>
          <small className="muted">
            At least 12 characters. Your password is never stored as plain text.
          </small>
          <button className="primary full" disabled={busy}>
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <ArrowRight size={16} />
            )}{" "}
            {signup ? "Create account" : "Sign in"}
          </button>
        </form>
        <div className="auth-links">
          <Link to="/explore">Explore public agents</Link>
          <Link to="/recover">Recover account</Link>
        </div>
        <button
          className="text-button"
          disabled={!registrationOpen}
          onClick={() => {
            setSignup(!signup);
            setError("");
          }}
        >
          {signup
            ? "Already have an account? Sign in"
            : registrationOpen
              ? "New to Tracy? Create an account"
              : "Registration is closed · contact the operator"}
        </button>
      </section>
    </div>
  );
}
export function AgentsPage() {
  const { agents, refresh } = useApp();
  const [error, setError] = useState("");
  async function toggle(a: Agent) {
    try {
      await api("/agents/" + a.agent_id + "/status", {
        method: "POST",
        body: JSON.stringify({ active: !a.active }),
      });
      await refresh();
    } catch (e) {
      setError(message(e));
    }
  }
  return (
    <>
      <Heading
        title="Your agents."
        text="Define the intent. Review the limits. Follow every action."
      />
      <div className="toolbar">
        <span>{agents.length} connected agents</span>
        <Link className="secondary" to="/agents/register">
          Connect SDK identity
        </Link>
        <Link className="primary" to="/agents/new">
          <Plus size={16} /> Create agent
        </Link>
      </div>
      <ErrorBox text={error} />
      {!agents.length ? (
        <div className="panel empty">
          <Bot size={36} />
          <h3>Describe your first agent</h3>
          <p>
            Start with its job, test the guardrails and review before
            deployment.
          </p>
          <Link className="primary" to="/agents/new">
            Create agent <ArrowRight size={16} />
          </Link>
        </div>
      ) : (
        <div className="agent-cards">
          {agents.map((a) => (
            <section className="panel agent-card" key={a.agent_id}>
              <div className="agent-card-head">
                <span className="agent-avatar">
                  <Bot size={24} />
                </span>
                <span
                  className={"badge " + (a.active ? "verified" : "rejected")}
                >
                  {a.active ? "ACTIVE" : "STOPPED"}
                </span>
              </div>
              <h2>
                <Link to={"/agents/" + a.agent_id}>{a.name}</Link>
              </h2>
              <p>{a.description || "No description yet."}</p>
              <code>{a.agent_id}</code>
              <div className="budget-label">
                <span>Daily budget · UTC</span>
                <b>
                  {fmt(a.budget.used_lamports / 1e9)} /{" "}
                  {fmt(a.policy.daily_budget_sol)} SOL
                </b>
              </div>
              <progress
                max={a.budget.limit_lamports}
                value={Math.min(
                  a.budget.used_lamports,
                  a.budget.limit_lamports,
                )}
              />
              <small>
                {fmt(a.budget.remaining_lamports / 1e9)} SOL remaining · Policy
                v{a.policy_version}
              </small>
              <div className="agent-card-actions">
                {a.managed && (
                  <Link className="primary" to={"/installed/" + a.agent_id}>
                    Run agent
                  </Link>
                )}
                <Link className="secondary" to={"/agents/" + a.agent_id}>
                  Manage agent <ArrowRight size={14} />
                </Link>
                <button className="secondary" onClick={() => void toggle(a)}>
                  {a.active ? <Pause size={14} /> : <Play size={14} />}{" "}
                  {a.active ? "Stop" : "Resume"}
                </button>
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
function PolicyFields({
  limit,
  setLimit,
  daily,
  setDaily,
  recipients,
  setRecipients,
  allowed,
  setAllowed,
}: {
  limit: string;
  setLimit: (v: string) => void;
  daily: string;
  setDaily: (v: string) => void;
  recipients: string;
  setRecipients: (v: string) => void;
  allowed: boolean;
  setAllowed: (v: boolean) => void;
}) {
  return (
    <>
      <div className="form-columns">
        <label>
          Maximum transfer (SOL)
          <input
            type="number"
            min="0.000000001"
            max="1000000"
            step="0.000000001"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            required
          />
        </label>
        <label>
          Daily budget (SOL)
          <input
            type="number"
            min="0.000000001"
            max="1000000"
            step="0.000000001"
            value={daily}
            onChange={(e) => setDaily(e.target.value)}
            required
          />
        </label>
      </div>
      <label>
        Allowed recipients
        <textarea
          aria-label="Allowed recipients"
          rows={3}
          placeholder="One Solana address per line"
          value={recipients}
          onChange={(e) => setRecipients(e.target.value)}
          required
        />
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={allowed}
          onChange={(e) => setAllowed(e.target.checked)}
        />{" "}
        Allow solana.transfer
      </label>
      <p className="form-help">
        The daily budget uses UTC and counts pending transfers. Network fees are
        separate. Lowering a budget does not erase spending already recorded.
      </p>
    </>
  );
}
function policy(
  limit: string,
  daily: string,
  recipients: string,
  allowed: boolean,
) {
  return {
    max_transfer_sol: Number(limit),
    daily_budget_sol: Number(daily),
    allowed_recipients: recipients.split(/[\s,]+/).filter(Boolean),
    allowed_actions: allowed ? ["solana.transfer"] : [],
  };
}
export function CreateAgent() {
  const { refresh, setSession } = useApp();
  const navigate = useNavigate();
  const [name, setName] = useState(""),
    [description, setDescription] = useState(""),
    [mode, setMode] = useState("browser"),
    [pk, setPk] = useState(""),
    [sdkId, setSdkId] = useState("");
  const [limit, setLimit] = useState("0.1"),
    [daily, setDaily] = useState("1"),
    [recipients, setRecipients] = useState(""),
    [allowed, setAllowed] = useState(true),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      let pair: CryptoKeyPair | undefined;
      let publicKey = pk.trim();
      if (mode === "browser") {
        pair = (await crypto.subtle.generateKey("Ed25519", false, [
          "sign",
          "verify",
        ])) as CryptoKeyPair;
        publicKey = base64(
          await crypto.subtle.exportKey("raw", pair.publicKey),
        );
      }
      const agent = await api<Agent>("/agents", {
        method: "POST",
        body: JSON.stringify({
          agent_id:
            mode === "sdk"
              ? sdkId.trim()
              : "agent_" + crypto.randomUUID().replaceAll("-", "").slice(0, 20),
          name,
          description,
          public_key: publicKey,
          policy: policy(limit, daily, recipients, allowed),
        }),
      });
      if (pair) setSession({ agent, key: pair.privateKey });
      await refresh();
      navigate("/agents/" + agent.agent_id);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Connect an agent."
        text="An identity, a signing key and explicit permission to act."
      />
      <ErrorBox text={error} />
      <form className="panel editor" onSubmit={submit}>
        <h2>Agent identity</h2>
        <label>
          Agent name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            required
            placeholder="Payout assistant"
          />
        </label>
        <label>
          Description
          <textarea
            aria-label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={1000}
            rows={2}
          />
        </label>
        <label>
          Signing key
          <select
            aria-label="Signing key"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="browser">Generate a browser demo key</option>
            <option value="sdk">Use my SDK public key</option>
          </select>
        </label>
        {mode === "sdk" ? (
          <>
            <label>
              SDK agent ID
              <input
                value={sdkId}
                onChange={(e) => setSdkId(e.target.value)}
                required
                placeholder="agent_id printed by keygen"
              />
            </label>
            <label>
              Ed25519 public key (base64)
              <input
                value={pk}
                onChange={(e) => setPk(e.target.value)}
                required
                placeholder="Public key printed by the SDK keygen command"
              />
            </label>
          </>
        ) : (
          <div className="notice">
            The demo private key stays in this tab. Refreshing or signing out
            ends its signing session. For a persistent bot, use an SDK key.
          </div>
        )}
        <h2>Spending policy</h2>
        <PolicyFields
          {...{
            limit,
            setLimit,
            daily,
            setDaily,
            recipients,
            setRecipients,
            allowed,
            setAllowed,
          }}
        />
        <button className="primary" disabled={busy}>
          {busy ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <Plus size={16} />
          )}{" "}
          Create agent
        </button>
      </form>
    </>
  );
}
type Version = { version: number; created_at: number; policy: Agent["policy"] };
export function AgentSettings() {
  const { id } = useParams();
  const { refresh, session } = useApp();
  const [agent, setAgent] = useState<Agent | null>(null),
    [versions, setVersions] = useState<Version[]>([]),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [name, setName] = useState(""),
    [description, setDescription] = useState(""),
    [limit, setLimit] = useState(""),
    [daily, setDaily] = useState(""),
    [recipients, setRecipients] = useState(""),
    [allowed, setAllowed] = useState(true);
  async function load() {
    const a = await api<Agent>("/agents/" + id);
    setAgent(a);
    setName(a.name);
    setDescription(a.description);
    setLimit(String(a.policy.max_transfer_sol));
    setDaily(String(a.policy.daily_budget_sol));
    setRecipients(a.policy.allowed_recipients.join("\n"));
    setAllowed(a.policy.allowed_actions.includes("solana.transfer"));
    setVersions(
      (await api<{ items: Version[] }>("/agents/" + id + "/policy/versions"))
        .items,
    );
  }
  useEffect(() => {
    void load().catch((e) => setError(message(e)));
  }, [id]);
  async function act(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      await load();
      await refresh();
      setNotice(success);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  if (!agent)
    return (
      <>
        <ErrorBox text={error} />
        <p>Loading agent…</p>
      </>
    );
  return (
    <>
      <Heading title={agent.name} text={agent.agent_id} />
      <ErrorBox text={error} />
      {notice && (
        <div className="verification-success" role="status">
          {notice}
        </div>
      )}
      <div className="toolbar">
        <span className={"badge " + (agent.active ? "verified" : "rejected")}>
          {agent.active ? "ACTIVE" : "STOPPED"}
        </span>
        <div className="button-row">
          {agent.managed && (
            <Link className="primary" to={"/installed/" + id}>
              Open installed agent
            </Link>
          )}
          {session?.agent.agent_id === id && (
            <Link className="primary" to="/demo">
              <Play size={14} /> Run signed action
            </Link>
          )}
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              void act(
                () =>
                  api("/agents/" + id + "/status", {
                    method: "POST",
                    body: JSON.stringify({ active: !agent.active }),
                  }),
                agent.active
                  ? "Agent stopped. New requests will be rejected."
                  : "Agent resumed.",
              )
            }
          >
            {agent.active ? <Pause size={14} /> : <Play size={14} />}{" "}
            {agent.active ? "Stop agent" : "Resume agent"}
          </button>
        </div>
      </div>
      <div className="stats">
        <div>
          <span>Daily limit</span>
          <strong>{fmt(agent.policy.daily_budget_sol)}</strong>
          <small>SOL · resets at 00:00 UTC</small>
        </div>
        <div>
          <span>Used / reserved</span>
          <strong>{fmt(agent.budget.used_lamports / 1e9)}</strong>
          <small>SOL · includes pending requests</small>
        </div>
        <div>
          <span>Remaining</span>
          <strong className="green">
            {fmt(agent.budget.remaining_lamports / 1e9)}
          </strong>
          <small>SOL today</small>
        </div>
        <div>
          <span>Current policy</span>
          <strong>v{agent.policy_version}</strong>
          <small>
            {agent.policy.allowed_recipients.length} allowed recipients
          </small>
        </div>
      </div>
      <div className="settings-grid">
        <form
          className="panel editor"
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              () =>
                api("/agents/" + id, {
                  method: "PATCH",
                  body: JSON.stringify({ name, description }),
                }),
              "Agent details saved.",
            );
          }}
        >
          <h2>Identity</h2>
          <label>
            Agent name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
            />
          </label>
          <label>
            Description
            <textarea
              aria-label="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={1000}
              rows={3}
            />
          </label>
          <label>
            Public signing key
            <input readOnly value={agent.public_key} />
          </label>
          <p className="form-help">
            The public key is fixed for this identity. Stopping an agent blocks
            new dispatches; a transaction already submitted cannot be recalled.
          </p>
          <button className="secondary" disabled={busy}>
            Save details
          </button>
        </form>
        <form
          className="panel editor"
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              () =>
                api("/agents/" + id + "/policy", {
                  method: "PUT",
                  body: JSON.stringify({
                    expected_version: agent.policy_version,
                    policy: policy(limit, daily, recipients, allowed),
                  }),
                }),
              "New policy version saved. Existing receipts are unchanged.",
            );
          }}
        >
          <h2>Policy v{agent.policy_version}</h2>
          <PolicyFields
            {...{
              limit,
              setLimit,
              daily,
              setDaily,
              recipients,
              setRecipients,
              allowed,
              setAllowed,
            }}
          />
          <button className="primary" disabled={busy}>
            Save new policy version
          </button>
        </form>
      </div>
      <section className="panel versions">
        <div className="panel-heading">
          <h2>Policy history</h2>
        </div>
        {versions.map((v) => (
          <details key={v.version}>
            <summary>
              Version {v.version}
              <span>
                {new Date(v.created_at * 1000).toLocaleString()} ·{" "}
                {v.policy.daily_budget_sol} SOL / day
              </span>
            </summary>
            <pre>{JSON.stringify(v.policy, null, 2)}</pre>
          </details>
        ))}
      </section>
      <PublicationPanel
        agent={agent}
        onSaved={async () => {
          await load();
          await refresh();
        }}
      />
      {!agent.managed && <OfferPanel agentId={agent.agent_id} />}
      {!agent.managed && <ConnectInstructions agent={agent} />}
    </>
  );
}
function ConnectInstructions({ agent }: { agent: Agent }) {
  return (
    <section className="panel editor connect-panel">
      <h2>
        <Terminal size={18} /> Connect from Python
      </h2>
      <p className="form-help">
        Use the private key corresponding to this registered public key. A
        browser demo key cannot be exported. To create a persistent bot, follow
        the SDK setup below with a new key.
      </p>
      <pre>
        {'from sdk.poa import PoAClient\nimport json, os\n\nkeys = json.load(open("data/my-agent.json"))\nwith PoAClient(api_key=os.environ["TRACY_API_KEY"]) as tracy:\n    result = tracy.transfer(\n        keys["private_seed"], "' +
          agent.agent_id +
          '",\n        "' +
          agent.policy.allowed_recipients[0] +
          '", 0.01,\n        request_id="payout_001",\n    )\n    print(result["status"])'}
      </pre>
      <Link className="secondary" to="/connect">
        SDK setup & personal API keys <ArrowRight size={15} />
      </Link>
    </section>
  );
}
export function ConnectPage() {
  const [keys, setKeys] = useState<
      {
        key_id: string;
        name: string;
        prefix: string;
        expires_at: number;
        revoked_at: number | null;
        scope: string;
      }[]
    >([]),
    [label, setLabel] = useState("Local payout bot"),
    [scope, setScope] = useState("manage"),
    [issued, setIssued] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const load = () =>
    api<{ items: typeof keys }>("/account/api-keys").then((r) =>
      setKeys(r.items),
    );
  useEffect(() => {
    void load().catch((e) => setError(message(e)));
  }, []);
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api<{ token: string }>("/account/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: label, scope }),
      });
      setIssued(r.token);
      await load();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Connect your bot."
        text="A personal API key manages your workspace. Your bot's Ed25519 key signs each action."
      />
      <ErrorBox text={error} />
      <div className="settings-grid">
        <section className="panel editor">
          <h2>1. Create a personal API key</h2>
          <p className="form-help">
            Each key belongs only to your account and expires after 30 days.
            Revoke it at any time. It grants access to your agents and settings.
          </p>
          <form onSubmit={create}>
            <label>
              Key name
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                required
                maxLength={80}
              />
            </label>
            <label>
              API key access
              <select
                aria-label="API key access"
                value={scope}
                onChange={(e) => setScope(e.target.value)}
              >
                <option value="manage">Manage workspace</option>
                <option value="read">Read-only access</option>
              </select>
            </label>
            <button className="primary" disabled={busy}>
              <KeyRound size={15} /> Create API key
            </button>
          </form>
          {issued && (
            <div className="issued-key">
              <label>
                Copy now — shown once
                <input readOnly value={issued} />
              </label>
              <button
                className="secondary"
                onClick={() => void navigator.clipboard.writeText(issued)}
              >
                Copy key
              </button>
            </div>
          )}
          <div className="key-list">
            {keys.map((k) => (
              <div key={k.key_id}>
                <div>
                  <strong>{k.name}</strong>
                  <small>
                    {k.scope} / {k.prefix}… ·{" "}
                    {k.revoked_at
                      ? "Revoked"
                      : "Expires " +
                        new Date(k.expires_at * 1000).toLocaleDateString()}
                  </small>
                </div>
                {!k.revoked_at && (
                  <button
                    className="text-button"
                    onClick={async () => {
                      try {
                        await api("/account/api-keys/" + k.key_id, {
                          method: "DELETE",
                        });
                        await load();
                        setIssued("");
                      } catch (e) {
                        setError(message(e));
                      }
                    }}
                  >
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>
        <section className="panel editor">
          <h2>2. Initialize a persistent agent</h2>
          <p className="form-help">
            Run from the project root in PowerShell. Replace the key and
            recipient. The SDK keeps your agent's private seed in the local
            file.
          </p>
          <pre>
            {
              '$env:TRACY_API_KEY = "YOUR_PERSONAL_API_KEY"\n\n.\\.venv\\Scripts\\python.exe -m sdk.poa init --name "Payout bot" --recipient RECIPIENT_ADDRESS --limit 0.1 --daily-budget 1 --key-file data/my-agent.json'
            }
          </pre>
          <h2>3. Send a signed request</h2>
          <pre>
            {
              ".\\.venv\\Scripts\\python.exe -m sdk.poa transfer --key-file data/my-agent.json --to RECIPIENT_ADDRESS --amount 0.01 --request-id payout_001"
            }
          </pre>
          <p className="form-help">
            Keep a stable request ID for retries of the same payout. A new ID
            creates a new operation. Transfers use the shared Devnet execution
            wallet in this release.
          </p>
          <Link className="secondary" to="/agents">
            View my agents <ArrowRight size={15} />
          </Link>
        </section>
      </div>
      <section className="panel editor">
        <h2>Bring an existing key</h2>
        <p className="form-help">
          Generate a key locally, then paste its agent ID and public key into
          <Link to="/agents/register">
            Connect SDK identity → Use my SDK public key
          </Link>
          .
        </p>
        <pre>
          {
            ".\\.venv\\Scripts\\python.exe -m sdk.poa keygen --key-file data/existing-agent.json"
          }
        </pre>
        <h2>Separate bot example</h2>
        <p className="form-help">
          The example payout bot reads a JSON job list, sends signed requests
          and resumes the same job IDs after a restart.
        </p>
        <pre>
          {
            ".\\.venv\\Scripts\\python.exe -m scripts.payout_bot --key-file data/my-agent.json --jobs examples/payout-jobs.json"
          }
        </pre>
      </section>
    </>
  );
}
export function LiveDemo() {
  const { session, refresh } = useApp();
  const [amount, setAmount] = useState("0.01"),
    [recipient, setRecipient] = useState(
      session?.agent.policy.allowed_recipients[0] || "",
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [result, setResult] = useState<Action | null>(null),
    [agent, setAgent] = useState<Agent | null>(session?.agent || null),
    [health, setHealth] = useState<{
      balance_lamports: number | null;
      rpc_available: boolean;
    } | null>(null),
    [config, setConfig] = useState<Config | null>(null);
  useEffect(() => {
    void api<Config>("/config")
      .then(setConfig)
      .catch((e) => setError(message(e)));
    void api<typeof health>("/health")
      .then(setHealth)
      .catch((e) => setError(message(e)));
    if (session)
      void api<Agent>("/agents/" + session.agent.agent_id)
        .then(setAgent)
        .catch((e) => setError(message(e)));
  }, [session]);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const signed = await signAction(
        session.key,
        session.agent.agent_id,
        recipient,
        Number(amount),
      );
      setResult(
        await api<Action>("/actions", {
          method: "POST",
          body: JSON.stringify(signed),
        }),
      );
      setAgent(await api<Agent>("/agents/" + session.agent.agent_id));
      await refresh();
    } catch (e) {
      setError(
        message(e) +
          " Check history before creating another request if a response was lost.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="From request to proof."
        text="Run a signed browser request through the same gateway as your SDK bot."
      />
      <ErrorBox text={error} />
      <div className="panel demo-wallet">
        <div>
          <span className="small-label">SHARED DEVNET EXECUTION WALLET</span>
          <code>{config?.execution_wallet || "Connecting…"}</code>
        </div>
        <div className="balance">
          {health?.balance_lamports != null
            ? fmt(health.balance_lamports / 1e9) + " SOL"
            : "Checking RPC…"}
        </div>
      </div>
      {!session ? (
        <section className="panel empty">
          <Bot size={36} />
          <h3>Create a browser demo agent</h3>
          <p>
            Your previous receipts are saved. Browser signing keys stay only in
            the tab where they were generated.
          </p>
          <Link className="primary" to="/agents/new">
            Create agent <Plus size={15} />
          </Link>
        </section>
      ) : (
        <div className="demo-grid">
          <form className="panel editor" onSubmit={submit}>
            <h2>{agent?.name}</h2>
            <p className="form-help">
              {agent?.active
                ? "Active"
                : "Stopped — new actions will be rejected"}{" "}
              · Policy v{agent?.policy_version} ·{" "}
              {fmt((agent?.budget.remaining_lamports || 0) / 1e9)} SOL remaining
              today
            </p>
            <Link
              className="text-button"
              to={"/agents/" + session.agent.agent_id}
            >
              Manage policy & status <ArrowRight size={14} />
            </Link>
            <label>
              Recipient address
              <input
                value={recipient}
                onChange={(e) => setRecipient(e.target.value.trim())}
                required
              />
            </label>
            <label>
              Amount (SOL)
              <input
                type="number"
                min="0.000000001"
                step="0.000000001"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
              />
            </label>
            <div className="amount-options">
              <button type="button" onClick={() => setAmount("0.01")}>
                0.01 SOL
              </button>
              <button
                type="button"
                onClick={() =>
                  setAmount(String((agent?.policy.max_transfer_sol || 0.1) + 1))
                }
              >
                Test policy rejection
              </button>
            </div>
            <div className="code-preview">
              <span>SIGNED AGENT INTENT</span>
              <code>
                solana.transfer
                <br />
                to: {short(recipient, 10)}
                <br />
                amount: {amount} SOL
              </code>
            </div>
            <button className="primary full" disabled={busy}>
              {busy ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <Play size={16} />
              )}{" "}
              {busy ? "Waiting for gateway…" : "Sign & execute action"}
            </button>
            <small className="form-note">
              Each click creates a new action. Allowed actions spend test SOL.
            </small>
          </form>
          <section className="panel editor">
            <h2>
              <ShieldCheck size={18} /> Gateway result
            </h2>
            <p className="form-help">
              Signature → timestamp → replay check → status & policy → budget
              reservation → execution → RPC evidence → receipt.
            </p>
            {busy && (
              <p className="pipeline-wait">
                <LoaderCircle className="spin" size={16} /> Waiting for actual
                gateway evidence…
              </p>
            )}
            {result ? (
              <div className="result-box">
                <span className={"badge " + result.status.toLowerCase()}>
                  {result.status}
                </span>
                <p>{result.reason.replaceAll("_", " ")}</p>
                {result.receipt_id ? (
                  <Link
                    className="primary full"
                    to={"/receipts/" + result.receipt_id}
                  >
                    Inspect proof receipt <ArrowRight size={16} />
                  </Link>
                ) : (
                  <button
                    className="secondary full"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        setResult(
                          await api<Action>(
                            "/actions/" + result.action_id + "/reconcile",
                            { method: "POST" },
                          ),
                        );
                        await refresh();
                      } catch (e) {
                        setError(message(e));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Check confirmation again
                  </button>
                )}
              </div>
            ) : (
              !busy && (
                <div className="waiting">
                  <Code2 size={32} /> Waiting for your signed request
                </div>
              )
            )}
          </section>
        </div>
      )}
    </>
  );
}
