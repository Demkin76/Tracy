import { TradingExchange, TradingLeaderboard } from "./ExchangePages";
import { Copilot, HelpCenter } from "./Copilot";
import { BrandMark } from "./BrandMark";
import {
  DeveloperStudio,
  StrategiesPage,
  MonitoringPage,
  PerformancePage,
  GuardrailsPage,
  TestsPage,
  AgentRoster,
  AgentIdentityPage,
} from "./WorkspaceSections";
import { AgentBuilder } from "./AgentBuilder";
import React, { createContext, useContext, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useLocation,
  useParams,
} from "react-router-dom";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  CheckCheck,
  ChevronRight,
  Circle,
  Copy,
  ExternalLink,
  Fingerprint,
  KeyRound,
  LayoutDashboard,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  Terminal,
  X,
} from "lucide-react";
import {
  Action,
  Agent,
  api,
  base64,
  Checks,
  Config,
  download,
  Receipt,
  short,
  signAction,
  verifyLocally,
} from "./api";
import "./styles.css";
import "./platform.css";
import "./lifecycle.css";
import {
  LifecycleOverview,
  StrategyCreatePage,
  StrategyDetail,
  DegradationPage,
  TradingIntentPage,
  TradingProofPage,
  InfrastructurePage,
  StrategyTestsPage,
  TradingProofIndex,
  TradingMethodology,
  TradingPublicAgent,
  TradingCompare,
} from "./LifecyclePages";
import {
  ControlHome,
  ControlAgent,
  IntentPage,
  ControlResources,
  ControlIntegrations,
} from "./ControlPages";
import {
  GettingStarted,
  InstalledAgents,
  InstallAgent,
  Installation,
} from "./MarketplacePages";
import { Globe, BarChart3, Bell, Settings, Wallet, Star } from "lucide-react";
import {
  PublicShell,
  Explore,
  PublicProfile,
  PublicProof,
  Compare,
  Methodology,
} from "./PublicPages";
import {
  ActivityPage,
  AnalyticsPage,
  WatchlistPage,
  NotificationsPage,
  FundingPage,
  SecurityPage,
  RecoveryPage,
  SharePanel,
} from "./WorkspacePages";
import { ApiError, setCsrf } from "./api";
import { Context, Session, User, useApp } from "./app-context";
import {
  AuthScreen,
  AgentsPage,
  CreateAgent,
  AgentSettings,
  ConnectPage,
  LiveDemo,
} from "./OwnerPages";

const date = (timestamp: number) => new Date(timestamp * 1000).toLocaleString();
function Badge({ status }: { status: string }) {
  return (
    <span className={"badge " + status.toLowerCase()}>
      {status === "VERIFIED" ? (
        <Check size={12} />
      ) : ["PENDING", "PREPARING"].includes(status) ? (
        <Circle size={10} />
      ) : (
        <X size={12} />
      )}{" "}
      {status}
    </span>
  );
}
function ErrorBox({ error }: { error: string }) {
  return error ? (
    <div className="error" role="alert">
      {error}
    </div>
  ) : null;
}
function CopyText({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy"
      title={"Copy " + value}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}
function App() {
  return (
    <BrowserRouter>
      <Workspace />
    </BrowserRouter>
  );
}
function Workspace() {
  const location = useLocation();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<Config | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  const refresh = async () => {
    try {
      const [c, a] = await Promise.all([
        api<Config>("/config"),
        api<{ items: Agent[] }>("/agents"),
      ]);
      setConfig(c);
      setAgents(a.items);
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setUser(null);
        setSession(null);
        setCsrf(null);
      } else setError(String(e));
    }
  };
  const restore = async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api<{ user: User; csrf_token: string }>("/auth/me");
      setCsrf(r.csrf_token);
      setUser(r.user);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void restore();
  }, []);
  useEffect(() => {
    if (user) void refresh();
  }, [user?.user_id]);
  const logout = async () => {
    try {
      await api("/auth/logout", { method: "POST" });
      setCsrf(null);
      setUser(null);
      setSession(null);
      setAgents([]);
    } catch (e) {
      setError(String(e));
    }
  };
  const publicPath =
    [
      "/",
      "/explore",
      "/leaderboard",
      "/compare",
      "/methodology",
      "/recover",
      "/help",
    ].includes(location.pathname) ||
    location.pathname.startsWith("/help/") ||
    location.pathname.startsWith("/exchange/") ||
    location.pathname.startsWith("/legacy/") ||
    location.pathname.startsWith("/a/") ||
    location.pathname.startsWith("/proof/") ||
    location.pathname.startsWith("/public/receipts/");
  if (publicPath)
    return (
      <PublicShell>
        <Copilot userId={user?.user_id} />
        <Routes>
          <Route path="/help" element={<HelpCenter />} />
          <Route path="/help/:topic" element={<HelpCenter />} />
          <Route path="/" element={<TradingExchange />} />
          <Route path="/explore" element={<Navigate to="/" replace />} />
          <Route path="/leaderboard" element={<TradingLeaderboard />} />
          <Route
            path="/exchange/strategies/:id"
            element={<StrategyDetail publicView />}
          />
          <Route
            path="/exchange/proofs/:id"
            element={<TradingProofPage publicView />}
          />
          <Route path="/legacy/explore" element={<Explore />} />
          <Route path="/legacy/agents/:id" element={<PublicProfile />} />
          <Route path="/legacy/compare" element={<Compare />} />
          <Route path="/a/:id" element={<TradingPublicAgent />} />
          <Route path="/compare" element={<TradingCompare />} />
          <Route path="/public/receipts/:id" element={<PublicProof />} />
          <Route path="/proof/:id" element={<PublicProof shared />} />
          <Route
            path="/methodology"
            element={<Navigate to="/help" replace />}
          />
          <Route path="/legacy/methodology" element={<Methodology />} />
          <Route path="/recover" element={<RecoveryPage />} />
        </Routes>
      </PublicShell>
    );
  if (loading)
    return (
      <div className="auth-loading">
        <LoaderCircle className="spin" /> Opening Tracy…
      </div>
    );
  if (!user)
    return error ? (
      <div className="auth-loading">
        <ErrorBox error={error} />
        <button onClick={() => void restore()}>Retry</button>
      </div>
    ) : (
      <AuthScreen onLogin={setUser} />
    );
  return (
    <Context.Provider
      value={{
        config,
        agents,
        refresh,
        session,
        setSession,
        user,
        logout,
        updateUser: setUser,
      }}
    >
      <div className="shell">
        <aside className="sidebar">
          <Link className="brand" to="/">
            <BrandMark />
            <span>
              tracy<span className="brand-dot">.</span>
            </span>
          </Link>
          <div className="workspace">
            <span className="workspace-avatar">
              {user.name.slice(0, 1).toUpperCase()}
            </span>
            <div>
              {user.name}
              <small>Trading workspace</small>
            </div>
            <span className="version">PAPER</span>
          </div>
          <div className="nav-label">EXCHANGE</div>
          <nav>
            <NavLink to="/" end>
              <Globe size={18} /> Agent marketplace
            </NavLink>
            <NavLink to="/leaderboard">
              <BarChart3 size={18} /> Leaderboard
            </NavLink>
            <NavLink to="/compare">
              <CheckCheck size={18} /> Compare agents
            </NavLink>
            <div className="nav-label">WORKSPACE</div>
            <NavLink to="/infrastructure">
              <ShieldCheck size={18} /> Guardrails
            </NavLink>
            <NavLink to="/developers">
              <Terminal size={18} /> Developer studio
            </NavLink>
            <NavLink to="/overview">
              <LayoutDashboard size={18} /> My workspace
            </NavLink>
            <NavLink to="/strategies">
              <Bot size={18} /> My strategies
            </NavLink>
            <NavLink to="/agents">
              <Fingerprint size={18} /> My instances
            </NavLink>
            <NavLink to="/tests">
              <Play size={18} /> Tests
            </NavLink>
            <NavLink to="/monitoring">
              <Activity size={18} /> Monitoring
            </NavLink>
            <NavLink to="/performance">
              <BarChart3 size={18} /> Performance
            </NavLink>
            <NavLink to="/degradation">
              <Bell size={18} /> Degradation alerts
            </NavLink>
            <NavLink to="/proofs">
              <CheckCheck size={18} /> Proofs
            </NavLink>
            <NavLink to="/help">
              <ShieldCheck size={18} /> Handbook
            </NavLink>
            <NavLink to="/security">
              <Settings size={18} /> Settings
            </NavLink>
          </nav>
          <div className="sidebar-bottom">
            <div className="network">
              <span className="dot" /> Binance Spot <span>PAPER</span>
            </div>
            <p>
              Recorded prices.
              <br />
              Verifiable paper fills.
            </p>
            <a href="/docs" target="_blank" rel="noreferrer">
              API documentation <ArrowUpRight size={15} />
            </a>
            <button className="logout" onClick={() => void logout()}>
              Sign out
            </button>
          </div>
        </aside>
        <div className="main-wrap">
          <header className="topbar">
            <span>
              Workspace <ChevronRight size={13} /> Tracy
            </span>
            <div>
              <span className="dot" /> Historical data / Paper trading{" "}
              <span className="avatar">
                {user.name.slice(0, 2).toUpperCase()}
              </span>
            </div>
          </header>
          <main>
            <Copilot userId={user.user_id} />
            <ErrorBox error={error} />
            {error && (
              <button className="secondary" onClick={() => void refresh()}>
                Retry connection
              </button>
            )}
            <Routes>
              <Route path="/developers" element={<DeveloperStudio />} />
              <Route path="/strategies" element={<StrategiesPage />} />
              <Route path="/strategies/new" element={<AgentBuilder />} />
              <Route
                path="/strategies/configure"
                element={<StrategyCreatePage />}
              />
              <Route path="/strategies/:id" element={<StrategyDetail />} />
              <Route path="/tests" element={<TestsPage />} />
              <Route path="/monitoring" element={<MonitoringPage />} />
              <Route path="/performance" element={<PerformancePage />} />
              <Route path="/degradation" element={<DegradationPage />} />
              <Route path="/infrastructure" element={<GuardrailsPage />} />
              <Route path="/proofs" element={<TradingProofIndex />} />
              <Route
                path="/trading/intents/:id"
                element={<TradingIntentPage />}
              />
              <Route path="/trades/:id/proof" element={<TradingProofPage />} />
              <Route path="/payouts" element={<Dashboard />} />
              <Route path="/control" element={<ControlHome />} />
              <Route
                path="/control/approvals"
                element={<ControlHome approvals />}
              />
              <Route path="/control/agents/:id" element={<ControlAgent />} />
              <Route path="/control/intents/:id" element={<IntentPage />} />
              <Route path="/control/resources" element={<ControlResources />} />
              <Route
                path="/control/integrations"
                element={<ControlIntegrations />}
              />
              <Route path="/overview" element={<LifecycleOverview />} />
              <Route path="/installed" element={<InstalledAgents />} />
              <Route path="/install/:id" element={<InstallAgent />} />
              <Route path="/installed/:id" element={<Installation />} />
              <Route path="/agents" element={<AgentRoster />} />
              <Route path="/agents/new" element={<AgentBuilder />} />
              <Route path="/agents/register" element={<CreateAgent />} />
              <Route path="/agents/:id" element={<AgentIdentityPage />} />
              <Route path="/demo" element={<LiveDemo />} />
              <Route path="/connect" element={<ConnectPage />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/watchlist" element={<WatchlistPage />} />
              <Route path="/notifications" element={<NotificationsPage />} />
              <Route path="/funding" element={<FundingPage />} />
              <Route path="/security" element={<SecurityPage />} />
              <Route path="/verify" element={<Lookup />} />
              <Route path="/receipts/:id" element={<ReceiptPage />} />
              <Route
                path="*"
                element={
                  <div className="empty">
                    Page not found. <Link to="/">Back to marketplace</Link>
                  </div>
                }
              />
            </Routes>
          </main>
          <footer>
            <span>
              <ShieldCheck size={14} /> Tracy · Proof of Action
            </span>
            <span>Agent marketplace. Verifiable paper records.</span>
          </footer>
        </div>
      </div>
    </Context.Provider>
  );
}
function Dashboard() {
  const { agents, config } = useApp();
  const [selected, setSelected] = useState(""),
    [items, setItems] = useState<Action[]>([]),
    [counts, setCounts] = useState<Record<string, number>>({}),
    [total, setTotal] = useState(0);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [filter, setFilter] = useState("All actions");
  const agentId = selected || agents[0]?.agent_id || "",
    agent = agents.find((a) => a.agent_id === agentId);
  const load = async () => {
    if (!agentId) return;
    setLoading(true);
    try {
      const data = await api<{
        items: Action[];
        counts: Record<string, number>;
        total: number;
      }>(`/agents/${agentId}/actions?limit=500`);
      setItems(data.items);
      setCounts(data.counts);
      setTotal(data.total);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, [agentId]);
  const visible = items.filter(
    (item) => filter === "All actions" || item.status === filter.toUpperCase(),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">AGENT OBSERVABILITY</div>
          <h1>Actions you can trust.</h1>
          <p>Every request checked. Every outcome independently verified.</p>
        </div>
        <Link className="primary" to="/demo">
          <Play size={15} /> Run live demo
        </Link>
      </div>
      <GettingStarted />
      <div className="hero">
        <div className="hero-content">
          <div className="hero-tag">
            <span className="dot" /> THE VERIFIABLE AGENT LAYER
          </div>
          <h2>
            Don't just take
            <br />
            your agent's word for it.
          </h2>
          <p>
            Turn an agent's intent into a signed, verifiable record of what
            actually happened.
          </p>
          <Link to="/explore">
            Choose an agent <ArrowRight size={17} />
          </Link>
        </div>
        <div className="flow-visual">
          <div className="visual-grid" />
          <div className="flow-node agent-node">
            <Bot size={25} />
            <span>
              Agent<span>Signed intent</span>
            </span>
          </div>
          <div className="connector">
            <span />
            <span />
            <span />
          </div>
          <div className="flow-node gateway-node">
            <ShieldCheck size={29} />
            <span>
              PoA Gateway<span>Policy · Execute · Verify</span>
            </span>
            <div className="node-check">
              <Check size={12} />
            </div>
          </div>
          <div className="connector">
            <span />
            <span />
            <span />
          </div>
          <div className="flow-node proof-node">
            <Fingerprint size={24} />
            <span>
              Proof receipt<span>Cryptographically signed</span>
            </span>
          </div>
          <div className="visual-caption">
            INTENT <span>→</span> ACTION <span>→</span> EVIDENCE
          </div>
        </div>
      </div>
      <div className="section-heading">
        <div>
          <h2>Agent overview</h2>
          <span>On-chain evidence, with a complete audit trail.</span>
        </div>
        <select
          aria-label="Select agent"
          value={agentId}
          onChange={(e) => setSelected(e.target.value)}
        >
          {!agents.length && <option value="">No agents registered</option>}
          {agents.map((a) => (
            <option key={a.agent_id} value={a.agent_id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>
      <div className="stats">
        <div>
          <span>
            Total requests <Activity size={17} />
          </span>
          <strong>{total.toString().padStart(2, "0")}</strong>
          <small>Signed requests received</small>
        </div>
        <div>
          <span>
            Verified actions <ShieldCheck size={17} />
          </span>
          <strong className="green">
            {(counts.VERIFIED || 0).toString().padStart(2, "0")}
          </strong>
          <small>Confirmed on Solana Devnet</small>
        </div>
        <div>
          <span>
            Policy rejections <KeyRound size={17} />
          </span>
          <strong>{(counts.REJECTED || 0).toString().padStart(2, "0")}</strong>
          <small>Blocked before execution</small>
        </div>
        <div>
          <span>
            Pending / failed <Activity size={17} />
          </span>
          <strong>
            {(
              (counts.PENDING || 0) +
              (counts.PREPARING || 0) +
              (counts.FAILED || 0)
            )
              .toString()
              .padStart(2, "0")}
          </strong>
          <small>Awaiting proof or need attention</small>
        </div>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>
            Action history <span className="count">{total}</span>
          </h2>
          <button
            className="icon-button"
            aria-label="Refresh actions"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={16} className={loading ? "spin" : ""} />
          </button>
        </div>
        <div className="tabs">
          {["All actions", "Verified", "Rejected", "Pending", "Failed"].map(
            (value) => (
              <button
                key={value}
                className={filter === value ? "active" : ""}
                onClick={() => setFilter(value)}
              >
                {value}
              </button>
            ),
          )}
        </div>
        <ErrorBox error={error} />
        {!visible.length ? (
          <div className="empty">
            <div className="empty-icon">
              <Fingerprint size={28} />
            </div>
            <h3>
              {loading
                ? "Loading actions…"
                : total
                  ? "No matching actions"
                  : "Your first action starts here"}
            </h3>
            <p>
              Register an agent and send a signed request.
              <br />
              Its receipt will appear in this feed.
            </p>
            <Link to="/demo">
              Open live demo <ArrowRight size={15} />
            </Link>
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>ACTION</th>
                  <th>RECIPIENT</th>
                  <th>STATUS</th>
                  <th>TIME</th>
                  <th>PROOF</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.action_id}>
                    <td>
                      <div className="table-action">
                        <span className="transfer-icon">
                          <ArrowUpRight size={18} />
                        </span>
                        <div>
                          {item.request.params.amount} <b>SOL</b>
                          <small>solana.transfer</small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <code title={item.request.params.to}>
                        {short(item.request.params.to)}
                      </code>
                    </td>
                    <td>
                      <Badge status={item.status} />
                    </td>
                    <td className="muted">{date(item.created_at)}</td>
                    <td>
                      {item.receipt_id ? (
                        <Link
                          className="proof-link"
                          to={"/receipts/" + item.receipt_id}
                        >
                          View <ArrowUpRight size={14} />
                        </Link>
                      ) : (
                        <button
                          className="text-button"
                          onClick={async () => {
                            try {
                              await api(
                                `/actions/${item.action_id}/reconcile`,
                                { method: "POST" },
                              );
                              await load();
                            } catch (e) {
                              setError(String(e));
                            }
                          }}
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
        )}
        {total > 500 && (
          <p className="notice">
            Showing the latest 500 requests. Full history is available through
            the paginated API.
          </p>
        )}
      </section>
      <div className="bottom-grid">
        <section className="panel policy-card">
          <div className="panel-heading">
            <h2>
              <KeyRound size={17} /> Active policy
            </h2>
            <span className="subtle-pill">
              {agent ? "ENFORCED" : "NOT CONFIGURED"}
            </span>
          </div>
          <dl>
            <div>
              <dt>Allowed action</dt>
              <dd>{agent?.policy.allowed_actions.join(", ") || "—"}</dd>
            </div>
            <div>
              <dt>Maximum transfer</dt>
              <dd>{agent ? agent.policy.max_transfer_sol + " SOL" : "—"}</dd>
            </div>
            <div>
              <dt>Recipient whitelist</dt>
              <dd>{agent?.policy.allowed_recipients.length || 0} wallets</dd>
            </div>
          </dl>
        </section>
        <section className="panel integrity-card">
          <ShieldCheck size={28} />
          <h3>Proof, not promises.</h3>
          <p>
            Each receipt is signed with Ed25519 and linked to the previous
            receipt with SHA-256.
          </p>
          <div className="wallet-label">
            EXECUTION WALLET{" "}
            <span>
              {config ? short(config.execution_wallet, 10) : "Connecting…"}
            </span>
            {config && <CopyText value={config.execution_wallet} />}
          </div>
        </section>
      </div>
    </>
  );
}
function Lookup() {
  const [id, setId] = useState("");
  const navigate = useNavigate();
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">INDEPENDENT VERIFICATION</div>
      </div>
      <section className="panel lookup">
        <div className="empty-icon">
          <ShieldCheck size={32} />
        </div>
        <h1>Verify a receipt.</h1>
        <p>Inspect the signature, hash chain and fresh blockchain evidence.</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            navigate("/receipts/" + encodeURIComponent(id.trim()));
          }}
        >
          <label>
            Receipt ID
            <input
              placeholder="poa_…"
              value={id}
              onChange={(e) => setId(e.target.value)}
              required
              pattern="poa_[a-zA-Z0-9]+"
            />
          </label>
          <button className="primary full">
            Open proof <ArrowRight size={16} />
          </button>
        </form>
      </section>
    </>
  );
}
function ReceiptPage() {
  const { id } = useParams();
  const { config } = useApp();
  const [receipt, setReceipt] = useState<Receipt | null>(null),
    [error, setError] = useState(""),
    [checks, setChecks] = useState<Checks | null>(null),
    [local, setLocal] = useState<boolean | null>(null),
    [busy, setBusy] = useState(false),
    [trusted, setTrusted] = useState("");
  useEffect(() => {
    setReceipt(null);
    setChecks(null);
    setLocal(null);
    setError("");
    api<Receipt>("/receipts/" + id)
      .then(setReceipt)
      .catch((e) => setError(String(e)));
  }, [id]);
  useEffect(() => {
    if (config) setTrusted(config.poa_public_key);
  }, [config]);
  async function verify() {
    if (!receipt) return;
    setBusy(true);
    setError("");
    setChecks(null);
    setLocal(null);
    try {
      const [remote, localResult] = await Promise.all([
        api<Checks>(`/receipts/${id}/verify`),
        verifyLocally(receipt, trusted),
      ]);
      setChecks(remote);
      setLocal(localResult);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!receipt)
    return (
      <>
        <ErrorBox error={error} />
        {!error && <div className="empty">Loading receipt…</div>}
        <Link to="/">Back to marketplace</Link>
      </>
    );
  return (
    <>
      <Link className="breadcrumb" to="/">
        Overview <ChevronRight size={13} /> Receipt
      </Link>
      <div className="page-heading">
        <div>
          <div className="eyebrow">CRYPTOGRAPHIC AUDIT RECORD</div>
          <h1>
            Tracy<span className="heading-dot">.</span>
          </h1>
          <p className="mono">{receipt.receipt_id}</p>
        </div>
        <button
          className="secondary"
          onClick={() => download(receipt, receipt.receipt_id + ".json")}
        >
          <ArrowDownToLine size={16} /> Export JSON
        </button>
      </div>
      <ErrorBox error={error} />
      <section className="panel receipt-summary">
        <div className={"receipt-symbol " + receipt.status.toLowerCase()}>
          {receipt.status === "VERIFIED" ? (
            <ShieldCheck size={34} />
          ) : (
            <Activity size={34} />
          )}
        </div>
        <div>
          <Badge status={receipt.status} />
          <h2>
            {receipt.status === "VERIFIED"
              ? "Action verified on-chain."
              : receipt.status === "REJECTED"
                ? "Policy stopped this action."
                : "Action could not be verified."}
          </h2>
          <p>
            {receipt.reason.replaceAll("_", " ")} · {date(receipt.timestamp)}
          </p>
        </div>
        <span className="network-pill">Solana Devnet</span>
      </section>
      <div className="receipt-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Action details</h2>
            <Fingerprint size={19} />
          </div>
          <dl className="receipt-details">
            <div>
              <dt>Agent</dt>
              <dd>
                {receipt.agent_name}
                <small>{receipt.agent_id}</small>
              </dd>
            </div>
            <div>
              <dt>Action</dt>
              <dd>
                Transfer {receipt.requested.amount} SOL
                <small>solana.transfer</small>
              </dd>
            </div>
            <div>
              <dt>Recipient</dt>
              <dd className="address">
                {receipt.requested.to}
                <CopyText value={receipt.requested.to} />
              </dd>
            </div>
            <div>
              <dt>Sender</dt>
              <dd className="address">
                {receipt.execution_wallet}
                <CopyText value={receipt.execution_wallet} />
              </dd>
            </div>
            <div>
              <dt>Transaction</dt>
              <dd>
                {receipt.result.tx_signature ? (
                  <a
                    className="address"
                    target="_blank"
                    rel="noreferrer"
                    href={
                      "https://explorer.solana.com/tx/" +
                      receipt.result.tx_signature +
                      "?cluster=devnet"
                    }
                  >
                    {short(receipt.result.tx_signature, 12)}{" "}
                    <ExternalLink size={14} />
                  </a>
                ) : (
                  "Not submitted"
                )}
              </dd>
            </div>
            <div>
              <dt>Policy</dt>
              <dd>
                {receipt.policy.approved ? "Allowed" : "Rejected"}
                {receipt.policy.version ? " / v" + receipt.policy.version : ""}
              </dd>
            </div>
            <div>
              <dt>Execution</dt>
              <dd>{receipt.result.status.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>RPC verification</dt>
              <dd>
                {receipt.verification.status.toUpperCase()}
                {receipt.verification.slot != null && (
                  <small>Confirmed slot {receipt.verification.slot}</small>
                )}
              </dd>
            </div>
          </dl>
        </section>
        <section className="panel verification-panel">
          <div className="panel-heading">
            <h2>
              <ShieldCheck size={18} /> Verify this proof
            </h2>
          </div>
          <div className="verification-body">
            <p>
              Check the signature in your browser and ask the gateway to
              independently re-read the blockchain.
            </p>
            <label>
              Trusted PoA public key
              <input
                className="mono"
                value={trusted}
                onChange={(e) => {
                  setTrusted(e.target.value);
                  setLocal(null);
                  setChecks(null);
                }}
              />
            </label>
            <small>
              Defaults to this gateway's published key. Pin an independently
              obtained key to verify its identity.
            </small>
            <button
              className="primary full"
              onClick={() => void verify()}
              disabled={busy || !trusted}
            >
              {busy ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <ShieldCheck size={16} />
              )}{" "}
              {busy ? "Checking evidence…" : "Verify receipt"}
            </button>
            {checks && (
              <div className="check-results" aria-live="polite">
                {[
                  ["Browser signature + hash", local],
                  ["Receipt hash", checks.hash_valid],
                  ["PoA signature", checks.signature_valid],
                  ["Agent request signature", checks.request_signature_valid],
                  ["Receipt chain", checks.chain_valid],
                  ["Fresh evidence", checks.evidence_valid],
                ].map(([label, valid]) => (
                  <div key={String(label)}>
                    <span>{label}</span>
                    <b
                      className={
                        valid === true
                          ? "green"
                          : valid === false
                            ? "red"
                            : "muted"
                      }
                    >
                      {valid === true
                        ? "Valid"
                        : valid === false
                          ? "Invalid"
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
                      ? "Valid signed policy rejection. No transfer was executed."
                      : "All checks passed. This proof is valid."
                    : "Verification is incomplete or failed. Do not treat this proof as verified."}
                </p>
                <small>
                  Evidence: {checks.evidence_status.replaceAll("_", " ")}
                </small>
              </div>
            )}
          </div>
        </section>
      </div>
      <SharePanel receiptId={receipt.receipt_id} />
      {receipt.policy.snapshot && (
        <section className="panel editor receipt-policy">
          <h2>Policy at the time of this action</h2>
          <p className="form-help">
            This snapshot and the gateway decision context are covered by the
            receipt signature. Later edits do not change this record.
          </p>
          <details>
            <summary>Inspect signed policy and decision</summary>
            <pre>{JSON.stringify(receipt.policy, null, 2)}</pre>
          </details>
        </section>
      )}
      <section className="panel chain-panel">
        <div className="panel-heading">
          <h2>Cryptographic provenance</h2>
          <button
            className="text-button"
            onClick={async () => {
              try {
                download(
                  await api(`/receipts/${id}/chain`),
                  `${id}-chain.json`,
                );
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            Export chain <ArrowDownToLine size={14} />
          </button>
        </div>
        <div className="hash-grid">
          <div>
            <span>PREVIOUS RECEIPT HASH</span>
            <code>
              {receipt.previous_receipt_hash ||
                "Genesis — first receipt in this agent’s chain"}
            </code>
          </div>
          <ArrowRight size={22} />
          <div>
            <span>RECEIPT HASH · #{receipt.sequence}</span>
            <code>{receipt.receipt_hash}</code>
          </div>
        </div>
        <p>Ed25519 signature · SHA-256 digest · RFC 8785 canonical JSON</p>
      </section>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
