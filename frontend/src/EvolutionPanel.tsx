import { useEffect, useState } from "react";
import { api } from "./api";
type Rule = {
  rule_id: string;
  probability: number;
  reason: string;
  expected_return_pct: number;
  evaluation_horizon_seconds: number;
  positive: number;
  negative: number;
  ignored: number;
};
type Change = {
  body: {
    revision: number;
    previous_revision: number;
    timestamp: number;
    reason: string;
    before: Rule[];
    after: Rule[];
    outcome_ids: string[];
    eligible_samples: number;
  };
};
type Outcome = {
  body: {
    decision_id: string;
    actual_return_pct: number;
    signal_return_pct: number;
    expected_return_pct: number;
    attribution: { reason: string; eligible_for_learning: boolean };
  };
};
type Evolution = {
  revision: number;
  original: Rule[];
  current: Rule[];
  changes: Change[];
  outcomes: Outcome[];
  pending: number;
};
export function EvolutionPanel({ agentId }: { agentId: string }) {
  const [value, setValue] = useState<Evolution | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Evolution>(`/adaptive/agents/${agentId}/evolution`)
        .then((v) => {
          if (alive) {
            setValue(v);
            setError("");
          }
        })
        .catch((e) => {
          if (alive) setError(String(e));
        });
    void load();
    const timer = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [agentId]);
  return (
    <section className="panel editor">
      <h2>Why did this agent change?</h2>
      {error && <p role="alert">{error}</p>}
      {value && (
        <>
          <p>
            APR revision {value.revision} · {value.pending} outcomes waiting for
            their horizon.
          </p>
          <p>
            Probabilities summarize attributed theses, not guaranteed profit.
            Execution anomalies, regime uncertainty and noise can be ignored.
          </p>
          <div className="adaptive-scroll">
            <table>
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Original</th>
                  <th>Agent</th>
                  <th>Supported / failed / ignored</th>
                  <th>Expected / horizon</th>
                </tr>
              </thead>
              <tbody>
                {value.current.map((r, i) => (
                  <tr key={r.rule_id}>
                    <td>{r.rule_id}</td>
                    <td>
                      {value.original[i]
                        ? `${(value.original[i].probability * 100).toFixed(1)}%`
                        : "Legacy baseline"}
                    </td>
                    <td>{(r.probability * 100).toFixed(1)}%</td>
                    <td>
                      {r.positive} / {r.negative} / {r.ignored}
                    </td>
                    <td>
                      {r.expected_return_pct}% /{" "}
                      {r.evaluation_horizon_seconds / 3600}h
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!value.changes.length && (
            <p>
              No attributed policy updates yet. Waiting for enough eligible
              observations.
            </p>
          )}
          {value.changes.map((c) => (
            <details key={c.body.revision}>
              <summary>
                APR v{c.body.previous_revision} → v{c.body.revision} ·{" "}
                {c.body.eligible_samples} eligible outcomes
              </summary>
              <p>{c.body.reason}</p>
              {c.body.after.map((r, i) => (
                <p key={r.rule_id}>
                  {r.rule_id}: {(c.body.before[i].probability * 100).toFixed(1)}
                  % → {(r.probability * 100).toFixed(1)}%. {r.reason}
                </p>
              ))}
              <p>Evidence: {c.body.outcome_ids.join(", ")}</p>
            </details>
          ))}
          <details>
            <summary>
              Outcome attribution ({value.outcomes.length} latest)
            </summary>
            {value.outcomes.map((o) => (
              <p key={o.body.decision_id}>
                <code>{o.body.decision_id}</code> · expected{" "}
                {o.body.expected_return_pct}% · signal{" "}
                {o.body.signal_return_pct.toFixed(3)}% · after modeled costs{" "}
                {o.body.actual_return_pct.toFixed(3)}% ·{" "}
                {o.body.attribution.reason} ·{" "}
                {o.body.attribution.eligible_for_learning
                  ? "Eligible"
                  : "Ignored"}
              </p>
            ))}
          </details>
        </>
      )}
    </section>
  );
}
