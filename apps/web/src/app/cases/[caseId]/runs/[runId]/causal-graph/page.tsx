"use client";

import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { CausalGraphResponse, CausalNode, reportsApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatPercent } from "@/lib/format";
import { Shell } from "@/components/Shell";

function nodeLabel(nodes: CausalNode[], nodeId: string): string {
  return nodes.find((node) => node.id === nodeId)?.label || nodeId;
}

export default function CausalGraphPage() {
  const {caseId, runId} = useParams<{caseId: string; runId: string}>();
  const [data, setData] = useState<CausalGraphResponse | null>(null);
  const [minConfidence, setMinConfidence] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(nextMinConfidence = minConfidence) {
    setLoading(true);
    setError(null);
    try {
      const response = await reportsApi.causalGraph(caseId, runId, {
        max_nodes: 100,
        min_confidence: nextMinConfidence,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(0);
  }, [caseId, runId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  const rootTemplateIds = useMemo(
    () => new Set((data?.root_cause_candidates || []).map((candidate) => candidate.template_id)),
    [data],
  );

  return (
    <Shell caseId={caseId} runId={runId}>
      <form className="toolbar" onSubmit={submit}>
        <h1>Causal Graph</h1>
        <label className="inline-field">
          Min confidence {formatPercent(minConfidence)}
          <input
            max="1"
            min="0"
            step="0.05"
            type="range"
            value={minConfidence}
            onChange={(event) => setMinConfidence(Number(event.target.value))}
          />
        </label>
        <button className="button secondary" disabled={loading} type="submit">Apply</button>
      </form>

      {error && <div className="alert error">{error}</div>}
      <section className="report-grid">
        <div className="panel graph-board">
          {loading && <div className="empty">Loading graph</div>}
          {!loading && data && data.nodes.length === 0 && <div className="empty">No graph nodes</div>}
          {!loading && data && data.nodes.length > 0 && (
            <>
              <div className="graph-node-list">
                {data.nodes.map((node) => (
                  <div
                    className={`node ${rootTemplateIds.has(node.template_id) ? "root" : ""}`}
                    key={node.id}
                  >
                    <strong>{node.label}</strong>
                    <br />
                    <span className="muted">
                      {node.golden_signal} · rank {formatPercent(node.rank_score)}
                    </span>
                    <br />
                    <span className="muted">
                      {node.occurrence_count} occurrences · first {formatDateTime(node.first_seen)}
                    </span>
                  </div>
                ))}
              </div>
              {data.edges.map((edge) => (
                <div className="edge" key={edge.id}>
                  {nodeLabel(data.nodes, edge.source)} {" -> "} {nodeLabel(data.nodes, edge.target)}
                </div>
              ))}
            </>
          )}
        </div>

        <div className="panel">
          <h2>Root Cause Candidates</h2>
          {!data?.root_cause_candidates.length && <div className="empty">No candidates</div>}
          {data?.root_cause_candidates.map((candidate) => (
            <p key={candidate.template_id}>
              <strong>#{candidate.rank}</strong> {candidate.reason}
              <br />
              <span className="muted">score {formatPercent(candidate.score)}</span>
            </p>
          ))}
        </div>
      </section>

      <section className="panel" style={{marginTop: 14}}>
        <h2>Candidate Edges</h2>
        {!loading && data && data.edges.length === 0 && <div className="empty">No edges match the filter</div>}
        {data && data.edges.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Edge</th>
                  <th>Method</th>
                  <th>Confidence</th>
                  <th>Validation</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {data.edges.map((edge) => (
                  <tr key={edge.id}>
                    <td>{nodeLabel(data.nodes, edge.source)} {" -> "} {nodeLabel(data.nodes, edge.target)}</td>
                    <td>{edge.method}</td>
                    <td>{formatPercent(edge.confidence)}</td>
                    <td>{edge.needs_validation ? "needs validation" : "validated"}</td>
                    <td><pre className="code-block">{JSON.stringify(edge.evidence, null, 2)}</pre></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </Shell>
  );
}
