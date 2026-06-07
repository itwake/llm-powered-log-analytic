"use client";

import cytoscape from "cytoscape";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  CausalGraphResponse,
  CausalNode,
  EvidenceRef,
  reportsApi,
} from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatPercent } from "@/lib/format";
import { Shell } from "@/components/Shell";

function nodeLabel(nodes: CausalNode[], nodeId: string): string {
  return nodes.find((node) => node.id === nodeId)?.label || nodeId;
}

function shortLabel(label: string): string {
  return label.length > 34 ? `${label.slice(0, 31)}...` : label;
}

function signalColor(signal: string): string {
  if (signal === "error") {
    return "#a6423c";
  }
  if (signal === "availability" || signal === "saturation") {
    return "#8b6728";
  }
  if (signal === "latency") {
    return "#654f9f";
  }
  return "#2d5f87";
}

function evidenceRefLabel(ref: EvidenceRef): string {
  const timestamp = ref.timestamp ? ` at ${formatDateTime(ref.timestamp)}` : "";
  return `${ref.file_path}:${ref.line_number}${timestamp}`;
}

function evidenceSummary(evidence: Record<string, unknown>): string {
  const entries = Object.entries(evidence).slice(0, 5);
  if (entries.length === 0) {
    return "No edge evidence";
  }
  return entries
    .map(([key, value]) => {
      const rendered = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value);
      return `${key}: ${rendered}`;
    })
    .join("\n");
}

type GraphElement = cytoscape.NodeSingular | cytoscape.EdgeSingular;

function nearestElement(cy: cytoscape.Core, point: cytoscape.Position): GraphElement | null {
  let nearest: GraphElement | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  cy.nodes().forEach((node) => {
    const position = node.renderedPosition();
    const distance = Math.hypot(position.x - point.x, position.y - point.y);
    if (distance < nearestDistance) {
      nearest = node;
      nearestDistance = distance;
    }
  });
  cy.edges().forEach((edge) => {
    const position = edge.renderedMidpoint();
    const distance = Math.hypot(position.x - point.x, position.y - point.y);
    if (distance < nearestDistance) {
      nearest = edge;
      nearestDistance = distance;
    }
  });
  return nearest;
}

type GraphSelection =
  | {kind: "node"; id: string}
  | {kind: "edge"; id: string}
  | null;

export default function CausalGraphPage() {
  const {caseId, runId} = useParams<{caseId: string; runId: string}>();
  const graphElement = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [data, setData] = useState<CausalGraphResponse | null>(null);
  const [minConfidence, setMinConfidence] = useState(0);
  const [selection, setSelection] = useState<GraphSelection>(null);
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
      setSelection(null);
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

  const graphElements = useMemo<cytoscape.ElementDefinition[]>(() => {
    if (!data) {
      return [];
    }
    const nodeIds = new Set(data.nodes.map((node) => node.id));
    return [
      ...data.nodes.map((node) => ({
        data: {
          id: node.id,
          label: shortLabel(node.label),
          fullLabel: node.label,
          signal: node.golden_signal,
          confidence: node.confidence,
          occurrenceCount: node.occurrence_count,
          rankScore: node.rank_score,
          color: signalColor(node.golden_signal),
        },
        classes: rootTemplateIds.has(node.template_id) ? "root-candidate" : "",
      })),
      ...data.edges
        .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
        .map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            edgeLabel: `${edge.method} ${formatPercent(edge.confidence)}`,
            method: edge.method,
            confidence: edge.confidence,
            needsValidation: edge.needs_validation,
          },
          classes: edge.needs_validation ? "needs-validation" : "",
        })),
    ];
  }, [data, rootTemplateIds]);

  const selectedNode = useMemo(
    () => selection?.kind === "node" ? data?.nodes.find((node) => node.id === selection.id) || null : null,
    [data, selection],
  );
  const selectedEdge = useMemo(
    () => selection?.kind === "edge" ? data?.edges.find((edge) => edge.id === selection.id) || null : null,
    [data, selection],
  );

  useEffect(() => {
    if (loading || !data || data.nodes.length === 0) {
      cyRef.current?.destroy();
      cyRef.current = null;
      return;
    }

    if (!graphElement.current) {
      return;
    }

    cyRef.current?.destroy();
    const cy = cytoscape({
      container: graphElement.current,
      elements: graphElements,
      layout: {
        name: "breadthfirst",
        directed: true,
        padding: 34,
        spacingFactor: 1.2,
        avoidOverlap: true,
      },
      maxZoom: 2.5,
      minZoom: 0.35,
      selectionType: "single",
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "background-opacity": (node: cytoscape.NodeSingular) => {
              const confidence = Number(node.data("confidence"));
              return Math.max(0.58, Math.min(1, confidence || 0));
            },
            "border-color": "#ffffff",
            "border-width": "2px",
            color: "#17201d",
            "font-size": "10px",
            height: "mapData(rankScore, 0, 1, 36, 72)",
            label: "data(label)",
            "min-zoomed-font-size": "8px",
            "overlay-padding": "5px",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.86,
            "text-background-padding": "3px",
            "text-margin-y": -8,
            "text-max-width": "110px",
            "text-valign": "top",
            "text-wrap": "wrap",
            width: "mapData(rankScore, 0, 1, 36, 72)",
          },
        },
        {
          selector: "node.root-candidate",
          style: {
            "border-color": "#a6423c",
            "border-width": "4px",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": "#17201d",
            "border-width": "5px",
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "font-size": "9px",
            label: "data(edgeLabel)",
            "line-color": "#6e7a73",
            "target-arrow-color": "#6e7a73",
            "target-arrow-shape": "triangle",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.82,
            "text-background-padding": "2px",
            width: "mapData(confidence, 0, 1, 1, 6)",
          },
        },
        {
          selector: "edge.needs-validation",
          style: {
            "line-style": "dashed",
          },
        },
        {
          selector: "edge:selected",
          style: {
            "line-color": "#17201d",
            "target-arrow-color": "#17201d",
            width: "5px",
          },
        },
      ],
      wheelSensitivity: 0.25,
    });
    cyRef.current = cy;

    const selectGraphNode = (nodeId: string) => {
      cy.elements().unselect();
      cy.getElementById(nodeId).select();
      setSelection({kind: "node", id: nodeId});
    };
    const selectGraphEdge = (edgeId: string) => {
      cy.elements().unselect();
      cy.getElementById(edgeId).select();
      setSelection({kind: "edge", id: edgeId});
    };

    cy.on("tap", "node", (event) => selectGraphNode(event.target.id()));
    cy.on("mouseover", "node", (event) => setSelection({kind: "node", id: event.target.id()}));
    cy.on("tap", "edge", (event) => selectGraphEdge(event.target.id()));
    cy.on("mouseover", "edge", (event) => setSelection({kind: "edge", id: event.target.id()}));
    cy.on("tap", (event) => {
      if (event.target !== cy) {
        return;
      }
      const nearest = nearestElement(cy, event.renderedPosition);
      if (!nearest) {
        return;
      }
      if (nearest.isNode()) {
        selectGraphNode(nearest.id());
      } else {
        selectGraphEdge(nearest.id());
      }
    });

    const resizeObserver = new ResizeObserver(() => cy.resize());
    resizeObserver.observe(graphElement.current);
    cy.ready(() => {
      cy.fit(undefined, 34);
    });

    return () => {
      resizeObserver.disconnect();
      cy.destroy();
      if (cyRef.current === cy) {
        cyRef.current = null;
      }
    };
  }, [data, graphElements, loading]);

  useEffect(() => () => {
    cyRef.current?.destroy();
    cyRef.current = null;
  }, []);

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
          {loading && <div className="empty graph-state">Loading graph</div>}
          {!loading && data && data.nodes.length === 0 && <div className="empty graph-state">No graph nodes</div>}
          {!loading && data && data.nodes.length > 0 && (
            <div
              aria-label="Causal directed graph"
              className="cytoscape-container"
              data-testid="cytoscape-graph"
              ref={graphElement}
            />
          )}
        </div>

        <div className="panel graph-side-panel">
          <div>
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

          <div className="graph-detail">
            <h2>Details</h2>
            {!selectedNode && !selectedEdge && (
              <p className="muted">Select a node or edge to inspect evidence.</p>
            )}
            {selectedNode && (
              <div data-testid="causal-detail-panel">
                <h3>{selectedNode.label}</h3>
                <dl className="detail-list">
                  <dt>Template</dt>
                  <dd>{selectedNode.template_id}</dd>
                  <dt>Signal</dt>
                  <dd>{selectedNode.golden_signal}</dd>
                  <dt>Occurrence</dt>
                  <dd>{selectedNode.occurrence_count}</dd>
                  <dt>Rank</dt>
                  <dd>{formatPercent(selectedNode.rank_score)}</dd>
                  <dt>Confidence</dt>
                  <dd>{formatPercent(selectedNode.confidence)}</dd>
                  <dt>First seen</dt>
                  <dd>{formatDateTime(selectedNode.first_seen)}</dd>
                </dl>
                <h3>Evidence Refs</h3>
                {selectedNode.evidence_refs.length === 0 && <p className="muted">No evidence refs</p>}
                {selectedNode.evidence_refs.slice(0, 4).map((ref) => (
                  <p className="muted evidence-ref" key={ref.log_id}>
                    {evidenceRefLabel(ref)}
                  </p>
                ))}
              </div>
            )}
            {selectedEdge && (
              <div data-testid="causal-detail-panel">
                <h3>
                  {nodeLabel(data?.nodes || [], selectedEdge.source)}
                  {" -> "}
                  {nodeLabel(data?.nodes || [], selectedEdge.target)}
                </h3>
                <dl className="detail-list">
                  <dt>Method</dt>
                  <dd>{selectedEdge.method}</dd>
                  <dt>Confidence</dt>
                  <dd>{formatPercent(selectedEdge.confidence)}</dd>
                  <dt>Validation</dt>
                  <dd>{selectedEdge.needs_validation ? "needs validation" : "validated"}</dd>
                  <dt>Lag</dt>
                  <dd>{selectedEdge.lag_seconds ?? "n/a"}</dd>
                  <dt>Support windows</dt>
                  <dd>{selectedEdge.support_windows}</dd>
                </dl>
                <h3>Evidence</h3>
                <pre className="code-block compact">{evidenceSummary(selectedEdge.evidence)}</pre>
              </div>
            )}
          </div>
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
