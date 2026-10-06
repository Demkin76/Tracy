import React, { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { BookOpen, MessageCircle, Send, X } from "lucide-react";
import { api } from "./api";
import { agentDefaults, type Configuration } from "./agent-config";
import "./copilot.css";

type Article = {
  id: string;
  title: string;
  body: string;
  ru: string;
  route: string;
};
export type CopilotResult = {
  answer: string;
  mode: string;
  articles: { id: string; title: string }[];
  navigate: string | null;
  questions: string[];
  proposal: {
    configuration: Configuration;
    changes: {
      field: string;
      before: unknown;
      after: unknown;
      source: string;
    }[];
    warnings: string[];
  } | null;
};
export function helpTopic(path: string, search = "") {
  if (path.startsWith("/bundles") || path.startsWith("/lab/bundles/")) return "bundles";
  if (path.startsWith("/lab")) return "adaptive";
  if (path.startsWith("/help/")) return path.split("/")[2];
  if (path.endsWith("/new")) return "intent";
  if (path.startsWith("/strategies/"))
    return (
      (
        {
          Tests: "backtests",
          Guardrails: "guardrails",
          Versions: "start",
          "Trades & proofs": "proofs",
        } as Record<string, string>
      )[new URLSearchParams(search).get("tab") || ""] || "performance"
    );
  return (
    (
      {
        "/tests": "backtests",
        "/infrastructure": "guardrails",
        "/monitoring": "replay",
        "/performance": "performance",
        "/degradation": "health",
        "/proofs": "proofs",
        "/security": "security",
        "/explore": "start",
        "/leaderboard": "leaderboard",
        "/compare": "leaderboard",
        "/developers": "publication",
        "/strategies": "publication",
      } as Record<string, string>
    )[path] || "start"
  );
}
export function HelpLink({
  topic,
  children,
}: {
  topic: string;
  children?: React.ReactNode;
}) {
  return (
    <Link className="help-link" to={"/help/" + topic}>
      <BookOpen size={15} />
      {children || "How this works"}
    </Link>
  );
}
const labels: Record<string, string> = {
  name: "Agent name",
  goal: "Intent",
  market: "Market",
  starting_capital: "Capital (USDC)",
  timeframe: "Candle interval",
  risk_tolerance: "Risk preference",
  "strategy_config.runner": "Strategy",
  "strategy_config.allocation_pct": "Capital per entry (%)",
  "guardrails.max_position_size": "Maximum position (USDC)",
  "guardrails.max_trade_size": "Maximum trade (USDC)",
  "guardrails.max_daily_loss": "Daily loss (%)",
  "guardrails.max_drawdown": "Drawdown (%)",
  "guardrails.human_approval_above": "Approval above (USDC)",
};
export function ProposalView({ result }: { result: CopilotResult }) {
  return (
    <>
      {result.proposal && (
        <div className="copilot-diff">
          <strong>Proposed draft changes</strong>
          {result.proposal.changes.map((c) => (
            <div key={c.field}>
              <span>{labels[c.field] || c.field}</span>
              <p>
                <del>
                  {typeof c.before === "number"
                    ? c.before.toLocaleString("en-US", {
                        maximumFractionDigits: 6,
                      })
                    : String(c.before || "Empty")}
                </del>{" "}
                →{" "}
                <b>
                  {typeof c.after === "number"
                    ? c.after.toLocaleString("en-US", {
                        maximumFractionDigits: 6,
                      })
                    : String(c.after)}
                </b>
              </p>
              <small>
                {c.source === "message"
                  ? "From your message"
                  : "Dependent adjustment / suggested value"}
              </small>
            </div>
          ))}
          {result.proposal.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      )}
      {result.questions.length > 0 && (
        <div className="copilot-questions">
          <strong>Check before continuing</strong>
          {result.questions.map((q, i) => (
            <p key={i}>{q}</p>
          ))}
        </div>
      )}
    </>
  );
}
export function HelpCenter() {
  const { topic } = useParams();
  const [articles, setArticles] = useState<Article[]>([]),
    [query, setQuery] = useState(""),
    [ru, setRu] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    api<{ items: Article[] }>("/help")
      .then((r) => setArticles(r.items))
      .catch((e) => setError(String(e)));
  }, []);
  const current = articles.find((a) => a.id === topic);
  return (
    <div className="handbook">
      <div className="page-heading">
        <div>
          <div className="eyebrow">TRACY HANDBOOK</div>
          <h1>{current?.title || "Product guide & methodology"}</h1>
          <p>
            Explain every result, setting and action. Ask Copilot about the page
            you are reading.
          </p>
        </div>
        <button className="secondary" onClick={() => setRu(!ru)}>
          {ru ? "Read in English" : "Читать по-русски"}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="handbook-layout">
        <nav aria-label="Handbook chapters">
          <label>
            Find an explanation
            <input
              aria-label="Search handbook"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Prices, limits, publication…"
            />
          </label>
          {articles
            .filter((a) =>
              (a.title + a.body + a.ru)
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((a) => (
              <Link
                className={a.id === topic ? "active" : ""}
                key={a.id}
                to={"/help/" + a.id}
              >
                {a.title}
              </Link>
            ))}
        </nav>
        <article className="panel handbook-article">
          {current ? (
            <>
              <div className="eyebrow">
                REFERENCE / {current.id.toUpperCase()}
              </div>
              <h2>{current.title}</h2>
              {(ru ? current.ru : current.body)
                .split(/(?<=\.)\s+(?=[A-ZА-Я])/)
                .map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              <Link className="primary" to={current.route}>
                Open this section →
              </Link>
            </>
          ) : (
            <>
              <h2>Find the explanation where you need it</h2>
              <p>
                Every workspace page has a “Help for this page” link. Each
                chapter describes the actual calculation or workflow, where its
                evidence comes from and what it does not prove.
              </p>
              {articles.map((a) => (
                <p key={a.id}>
                  <Link to={"/help/" + a.id}>{a.title} →</Link>
                </p>
              ))}
            </>
          )}
        </article>
      </div>
    </div>
  );
}

type ChatTurn = {
  role: "user" | "assistant";
  content: string;
  result?: CopilotResult;
  base?: string;
  applied?: boolean;
};
export function Copilot({ userId }: { userId?: string }) {
  const location = useLocation(),
    navigate = useNavigate();
  const storage = "tracy-copilot:" + (userId || "guest");
  const [open, setOpen] = useState(() => {
      try {
        return sessionStorage.getItem("tracy-copilot-open") === "1";
      } catch {
        return false;
      }
    }),
    [messages, setMessages] = useState<ChatTurn[]>([]),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [provider, setProvider] = useState("AI provider"),
    [available, setAvailable] = useState(false),
    [useAI, setUseAI] = useState(false);
  const bottom = useRef<HTMLDivElement>(null),
    epoch = useRef(0);
  useEffect(() => {
    epoch.current++;
    try {
      setMessages(JSON.parse(sessionStorage.getItem(storage) || "[]"));
    } catch {
      setMessages([]);
    }
    setUseAI(false);
    setError("");
  }, [storage]);
  useEffect(() => {
    api<{ ai_available: boolean; provider: string | null }>("/copilot/status")
      .then((r) => {
        setAvailable(r.ai_available);
        setProvider(r.provider || "AI provider");
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    document.body.classList.toggle("copilot-open", open);
    try {
      sessionStorage.setItem("tracy-copilot-open", open ? "1" : "0");
    } catch {}
    return () => document.body.classList.remove("copilot-open");
  }, [open]);
  useEffect(() => {
    if (open) bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages, busy, open]);
  function remember(turns: ChatTurn[]) {
    setMessages(turns);
    try {
      sessionStorage.setItem(storage, JSON.stringify(turns.slice(-16)));
    } catch {}
  }
  function draft(): Configuration {
    try {
      return (
        JSON.parse(
          sessionStorage.getItem("tracy-agent-draft:" + userId) || "null",
        ) || agentDefaults()
      );
    } catch {
      return agentDefaults();
    }
  }
  async function send(text = message) {
    if (!text.trim() || busy) return;
    const requestEpoch = epoch.current;
    const base =
      userId &&
      !/^\/(strategies|exchange\/strategies)\/[^/]+/.test(
        location.pathname.replace(/\/new$/, ""),
      )
        ? draft()
        : null;
    const next: ChatTurn[] = [...messages, { role: "user", content: text }];
    remember(next);
    setMessage("");
    setBusy(true);
    setError("");
    try {
      const result = await api<CopilotResult>("/copilot/message", {
        method: "POST",
        body: JSON.stringify({
          message: text,
          page: location.pathname + location.search,
          draft: base,
          history: messages
            .slice(-8)
            .map((m) => ({ role: m.role, content: m.content.slice(0, 3000) })),
          use_ai: useAI,
        }),
      });
      if (requestEpoch !== epoch.current) return;
      remember([
        ...next,
        {
          role: "assistant",
          content: result.answer,
          result,
          base: base ? JSON.stringify(base) : undefined,
        },
      ]);
      if (result.navigate) navigate(result.navigate);
    } catch (e) {
      if (requestEpoch === epoch.current) setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function apply(index: number) {
    const turn = messages[index];
    if (!userId || !turn.result?.proposal) return;
    if (JSON.stringify(draft()) !== turn.base) {
      setError(
        "Your draft changed since this suggestion. Ask again using the current settings.",
      );
      return;
    }
    const config = turn.result.proposal.configuration;
    try {
      sessionStorage.setItem(
        "tracy-agent-draft:" + userId,
        JSON.stringify(config),
      );
      sessionStorage.setItem(
        "tracy-copilot-pending:" + userId,
        JSON.stringify(config),
      );
    } catch {
      setError(
        "Browser storage is unavailable. Copy these values into the form manually.",
      );
      return;
    }
    remember(
      messages.map((t, i) => (i === index ? { ...t, applied: true } : t)),
    );
    navigate("/agents/new?copilot=" + Date.now());
  }
  const topic = helpTopic(location.pathname, location.search);
  return (
    <>
      <div className="assistance-tools">
        <HelpLink topic={topic}>Help for this page</HelpLink>
        <button
          className="copilot-launch"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <MessageCircle size={18} /> Tracy Copilot
        </button>
      </div>
      {open && (
        <aside className="copilot-panel" aria-label="Tracy Copilot">
          <header>
            <div>
              <strong>Tracy Copilot</strong>
              <small>
                {useAI && available
                  ? "AI · grounded in Tracy"
                  : "Built-in guide & form commands"}
              </small>
            </div>
            <button aria-label="Close Copilot" onClick={() => setOpen(false)}>
              <X size={18} />
            </button>
          </header>
          <div className="copilot-context">
            <HelpLink topic={topic} />
            {available && userId ? (
              <label>
                <input
                  type="checkbox"
                  checked={useAI}
                  onChange={(e) => setUseAI(e.target.checked)}
                />{" "}
                Use {provider} — sends messages, draft and page summary to{" "}
                {provider}
              </label>
            ) : (
              <p>
                Reference mode: explanations and supported commands. Free-form
                AI requires a configured provider.
              </p>
            )}
            {available && provider === "Gemini" && (
              <p>
                Google’s free tier may use submitted content to improve its
                products. Quotas apply.
              </p>
            )}
          </div>
          <div className="copilot-messages" aria-live="polite">
            {!messages.length && (
              <div className="copilot-welcome">
                <h3>What would you like to understand?</h3>
                <p>
                  I can explain this page, take you to a section or prepare
                  draft settings for review.
                </p>
                {[
                  "Explain this page",
                  "Where do historical prices come from?",
                  "Open guardrails",
                ].map((t) => (
                  <button
                    className="secondary"
                    key={t}
                    onClick={() => void send(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}
            {messages.map((turn, i) => (
              <div className={"copilot-message " + turn.role} key={i}>
                <small>{turn.role === "user" ? "You" : "Tracy"}</small>
                <p>{turn.content}</p>
                {turn.result && (
                  <>
                    <ProposalView result={turn.result} />
                    {turn.result.proposal && (
                      <button
                        className="primary"
                        disabled={turn.applied || busy}
                        onClick={() => apply(i)}
                      >
                        {turn.applied
                          ? "Applied to draft"
                          : "Apply to draft & open form"}
                      </button>
                    )}
                    <div className="copilot-citations">
                      {turn.result.articles.map((a) => (
                        <Link key={a.id} to={"/help/" + a.id}>
                          {a.title} →
                        </Link>
                      ))}
                    </div>
                  </>
                )}
              </div>
            ))}
            {busy && <p role="status">Reading the page and your request…</p>}
            {error && (
              <p role="alert" className="copilot-error">
                {error}
              </p>
            )}
            <div ref={bottom} />
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <label htmlFor="copilot-input">
              Ask Tracy
              <textarea
                id="copilot-input"
                value={message}
                maxLength={3000}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Explain this number, open tests, or set capital to 1000 USDC…"
                rows={3}
              />
            </label>
            <div>
              <button
                type="button"
                className="text-button"
                disabled={busy}
                onClick={() => remember([])}
              >
                Clear chat
              </button>
              <button className="primary" disabled={busy || !message.trim()}>
                <Send size={15} /> Send
              </button>
            </div>
          </form>
        </aside>
      )}
    </>
  );
}
