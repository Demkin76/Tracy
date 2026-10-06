import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "./api";
import { EvolutionPanel } from "./EvolutionPanel";

type Item = {
  id: string;
  kind: string;
  name: string;
  market: string;
  creator_id: string;
  creator_name: string;
  revision: number;
  url: string;
  gate_passed: boolean | null;
};
export function UnifiedMarketplace() {
  const [items, setItems] = useState<Item[]>([]),
    [kind, setKind] = useState("all"),
    [q, setQ] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    api<{ items: Item[] }>("/public/catalog")
      .then((v) => setItems(v.items))
      .catch((e) => setError(String(e)));
  }, []);
  return (
    <div className="adaptive-page">
      <header>
        <div className="eyebrow">TRACY MARKETPLACE</div>
        <h1>Strategies and learned agents</h1>
        <p>
          Inspect the original rules, evidence and accumulated learning before
          creating your own instance.
        </p>
        <Link to="/lab">Build and train →</Link>
      </header>
      {error && <p role="alert">{error}</p>}
      <section className="panel editor">
        <label>
          Find a strategy or Bundle
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="all">All</option>
            <option value="strategy">Strategy</option>
            <option value="bundle">Learned Bundle</option>
          </select>
        </label>
      </section>
      {items
        .filter(
          (i) =>
            (kind === "all" || i.kind === kind) &&
            `${i.name} ${i.market} ${i.creator_name}`
              .toLowerCase()
              .includes(q.toLowerCase()),
        )
        .map((i) => (
          <section className="panel editor" key={i.id}>
            <div className="eyebrow">
              {i.kind} · revision {i.revision}
            </div>
            <h2>
              <Link to={i.url}>{i.name}</Link>
            </h2>
            <p>
              {i.market} · by{" "}
              <Link to={"/creators/" + i.creator_id}>{i.creator_name}</Link>
            </p>
            <p>
              {i.gate_passed === true
                ? "Candidate passed its recorded holdout"
                : "Inspect available evidence; no improvement claimed"}
            </p>
          </section>
        ))}
      {!items.length && !error && (
        <p>
          No public work yet. Publication requires an explicit author action.
        </p>
      )}
    </div>
  );
}
export function CreatorPage() {
  const { id } = useParams();
  const [v, setV] = useState<{
      name: string;
      items: Item[];
      metrics: Record<string, number>;
      note: string;
    } | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    api<typeof v>("/public/creators/" + id)
      .then(setV)
      .catch((e) => setError(String(e)));
  }, [id]);
  return (
    <div className="adaptive-page">
      <Link to="/bundles">← Marketplace</Link>
      {error && <p role="alert">{error}</p>}
      {v && (
        <>
          <h1>{v.name}</h1>
          <section className="panel editor">
            {Object.entries(v.metrics).map(([k, n]) => (
              <p key={k}>
                {k.replaceAll("_", " ")}: {n}
              </p>
            ))}
            <p>{v.note}</p>
          </section>
          {v.items.map((i) => (
            <p key={i.id}>
              <Link to={i.url}>{i.name}</Link> · {i.kind}
            </p>
          ))}
        </>
      )}
    </div>
  );
}
export function CloneComparison() {
  const [query] = useSearchParams();
  const first = query.get("first"),
    second = query.get("second");
  const [v, setV] = useState<{
      source_bundle: string;
      agents: { agent_id: string; name: string }[];
      note: string;
    } | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    api<typeof v>(
      `/adaptive/compare?first=${encodeURIComponent(first || "")}&second=${encodeURIComponent(second || "")}`,
    )
      .then(setV)
      .catch((e) => setError(String(e)));
  }, [first, second]);
  return (
    <div className="adaptive-page">
      <h1>One Bundle, two independent agents</h1>
      {error && <p role="alert">{error}</p>}
      {v && (
        <>
          <p>{v.note}</p>
          <div className="adaptive-compare">
            {v.agents.map((a) => (
              <div key={a.agent_id}>
                <h2>
                  <Link to={"/lab/" + a.agent_id}>{a.name}</Link>
                </h2>
                <p>Review and start this instance from its page.</p>
                <EvolutionPanel agentId={a.agent_id} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
export function BundleIntelligence({ id }: { id: string }) {
  const [v, setV] = useState<{
      public_descendants: number;
      minimum_cohort: number;
      rules: {
        rule_id: string;
        median_probability: number;
        min_probability: number;
        max_probability: number;
      }[];
      note: string;
    } | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    api<typeof v>(`/public/bundles/${id}/intelligence`)
      .then(setV)
      .catch((e) => setError(String(e)));
  }, [id]);
  return (
    <section className="panel editor">
      <h2>Bundle intelligence</h2>
      {error && <p>{error}</p>}
      {v && (
        <>
          <p>
            {v.public_descendants} public descendant snapshots · minimum cohort{" "}
            {v.minimum_cohort}
          </p>
          {v.rules.map((r) => (
            <p key={r.rule_id}>
              {r.rule_id}: median {(r.median_probability * 100).toFixed(1)}% ·
              range {(r.min_probability * 100).toFixed(1)}–
              {(r.max_probability * 100).toFixed(1)}%
            </p>
          ))}
          {!v.rules.length && (
            <p>
              Not enough public descendants to publish aggregate policy
              statistics.
            </p>
          )}
          <p>{v.note}</p>
        </>
      )}
    </section>
  );
}
