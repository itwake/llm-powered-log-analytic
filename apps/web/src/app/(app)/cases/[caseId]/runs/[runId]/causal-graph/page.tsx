"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import cytoscape from "cytoscape";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  CausalEdge,
  CausalGraphResponse,
  CausalNode,
  EvidenceRef,
  reportsApi,
} from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatPercent } from "@/lib/format";
import { Badge, Button, Card, EmptyState } from "@/components/ui";

function nodeLabel(nodes: CausalNode[], nodeId: string): string {
  return nodes.find((node) => node.id === nodeId)?.label || nodeId;
}

function shortLabel(label: string): string {
  return label.length > 34 ? `${label.slice(0, 31)}...` : label;
}

function signalColor(
  signal: string,
  colors: { error: string; warning: string; latency: string; primary: string },
): string {
  if (signal === "error") {
    return colors.error;
  }
  if (signal === "availability" || signal === "saturation") {
    return colors.warning;
  }
  if (signal === "latency") {
    return colors.latency;
  }
  return colors.primary;
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
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

function DetailList({ children }: { children: ReactNode }) {
  return (
    <Box
      component="dl"
      sx={{
        display: "grid",
        gap: 1,
        gridTemplateColumns: "130px minmax(0, 1fr)",
        m: 0,
        "& dt": { color: "text.secondary" },
        "& dd": { m: 0, overflowWrap: "anywhere" },
      }}
    >
      {children}
    </Box>
  );
}

export default function CausalGraphPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const theme = useTheme();
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

  const signalColors = useMemo(
    () => ({
      error: theme.palette.error.main,
      warning: theme.palette.warning.main,
      latency: theme.palette.secondary.main,
      primary: theme.palette.primary.main,
    }),
    [theme],
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
          color: signalColor(node.golden_signal, signalColors),
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
  }, [data, rootTemplateIds, signalColors]);

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
            color: theme.palette.text.primary,
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
            "border-color": theme.palette.error.main,
            "border-width": "4px",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": theme.palette.text.primary,
            "border-width": "5px",
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "font-size": "9px",
            label: "data(edgeLabel)",
            "line-color": theme.palette.text.secondary,
            "target-arrow-color": theme.palette.text.secondary,
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
            "line-color": theme.palette.text.primary,
            "target-arrow-color": theme.palette.text.primary,
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
      setSelection({ kind: "node", id: nodeId });
    };
    const selectGraphEdge = (edgeId: string) => {
      cy.elements().unselect();
      cy.getElementById(edgeId).select();
      setSelection({ kind: "edge", id: edgeId });
    };

    cy.on("tap", "node", (event) => selectGraphNode(event.target.id()));
    cy.on("mouseover", "node", (event) => setSelection({ kind: "node", id: event.target.id() }));
    cy.on("tap", "edge", (event) => selectGraphEdge(event.target.id()));
    cy.on("mouseover", "edge", (event) => setSelection({ kind: "edge", id: event.target.id() }));
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
  }, [data, graphElements, loading, theme]);

  useEffect(() => () => {
    cyRef.current?.destroy();
    cyRef.current = null;
  }, []);

  const edgeColumns = useMemo<GridColDef<CausalEdge>[]>(
    () => [
      {
        field: "edge",
        headerName: "Edge",
        flex: 1,
        minWidth: 280,
        renderCell: (params) => (
          <Typography sx={{ overflowWrap: "anywhere", whiteSpace: "normal" }} variant="body2">
            {nodeLabel(data?.nodes || [], params.row.source)} {" -> "} {nodeLabel(data?.nodes || [], params.row.target)}
          </Typography>
        ),
      },
      {
        field: "method",
        headerName: "Method",
        minWidth: 140,
        renderCell: (params) => <Badge tone="info">{params.row.method}</Badge>,
      },
      {
        field: "confidence",
        headerName: "Confidence",
        minWidth: 130,
        renderCell: (params) => formatPercent(params.row.confidence),
      },
      {
        field: "needs_validation",
        headerName: "Validation",
        minWidth: 150,
        renderCell: (params) => (
          <Badge tone={params.row.needs_validation ? "warning" : "success"}>
            {params.row.needs_validation ? "needs validation" : "validated"}
          </Badge>
        ),
      },
      {
        field: "evidence",
        headerName: "Evidence",
        flex: 1.1,
        minWidth: 300,
        sortable: false,
        renderCell: (params) => (
          <Box
            component="pre"
            sx={{
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
              fontSize: 12,
              m: 0,
              maxHeight: 180,
              overflow: "auto",
              whiteSpace: "pre-wrap",
            }}
          >
            {JSON.stringify(params.row.evidence, null, 2)}
          </Box>
        ),
      },
    ],
    [data],
  );

  return (
    <Stack spacing={2.5}>
      <Stack
        component="form"
        direction={{ xs: "column", lg: "row" }}
        spacing={2}
        sx={{ alignItems: { xs: "flex-start", lg: "center" }, justifyContent: "space-between" }}
        onSubmit={submit}
      >
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          Causal Graph
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { xs: "stretch", sm: "center" }, width: { xs: "100%", lg: "auto" } }}>
          <Box component="label" sx={{ color: "text.secondary", display: "grid", gap: 0.5, minWidth: 260 }}>
            <Typography component="span" variant="caption">
              Min confidence {formatPercent(minConfidence)}
            </Typography>
            <Box
              component="input"
              max="1"
              min="0"
              step="0.05"
              type="range"
              value={minConfidence}
              onChange={(event) => setMinConfidence(Number(event.target.value))}
            />
          </Box>
          <Button disabled={loading} type="submit" variant="secondary">
            Apply
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", xl: "minmax(0, 1.5fr) minmax(360px, 0.8fr)" } }}>
        <Card>
          {loading && <EmptyState title="Loading graph" />}
          {!loading && data && data.nodes.length === 0 && <EmptyState title="No graph nodes" />}
          {!loading && data && data.nodes.length > 0 && (
            <Box
              aria-label="Causal directed graph"
              className="cytoscape-container"
              data-testid="cytoscape-graph"
              ref={graphElement}
            />
          )}
        </Card>

        <Stack spacing={2}>
          <Card>
            <Stack spacing={1.5}>
              <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                Root Cause Candidates
              </Typography>
              {!data?.root_cause_candidates.length && <EmptyState title="No candidates" />}
              {data?.root_cause_candidates.map((candidate) => (
                <Box key={candidate.template_id} sx={{ border: 1, borderColor: "divider", borderRadius: "10px", p: 1.5 }}>
                  <Typography sx={{ fontWeight: 800 }}>#{candidate.rank} {candidate.reason}</Typography>
                  <Typography color="text.secondary" variant="caption">score {formatPercent(candidate.score)}</Typography>
                </Box>
              ))}
            </Stack>
          </Card>

          <Card>
            <Stack spacing={2}>
              <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                Details
              </Typography>
              {!selectedNode && !selectedEdge && (
                <Typography color="text.secondary">Select a node or edge to inspect evidence.</Typography>
              )}
              {selectedNode && (
                <Stack data-testid="causal-detail-panel" spacing={2}>
                  <Typography component="h3" sx={{ fontWeight: 800 }} variant="subtitle1">
                    {selectedNode.label}
                  </Typography>
                  <DetailList>
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
                  </DetailList>
                  <Typography component="h3" sx={{ fontWeight: 800 }} variant="subtitle1">
                    Evidence Refs
                  </Typography>
                  {selectedNode.evidence_refs.length === 0 && <Typography color="text.secondary">No evidence refs</Typography>}
                  {selectedNode.evidence_refs.slice(0, 4).map((ref) => (
                    <Typography color="text.secondary" key={ref.log_id} sx={{ overflowWrap: "anywhere" }} variant="body2">
                      {evidenceRefLabel(ref)}
                    </Typography>
                  ))}
                </Stack>
              )}
              {selectedEdge && (
                <Stack data-testid="causal-detail-panel" spacing={2}>
                  <Typography component="h3" sx={{ fontWeight: 800 }} variant="subtitle1">
                    {nodeLabel(data?.nodes || [], selectedEdge.source)}
                    {" -> "}
                    {nodeLabel(data?.nodes || [], selectedEdge.target)}
                  </Typography>
                  <DetailList>
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
                  </DetailList>
                  <Typography component="h3" sx={{ fontWeight: 800 }} variant="subtitle1">
                    Evidence
                  </Typography>
                  <Box component="pre" className="code-block compact">
                    {evidenceSummary(selectedEdge.evidence)}
                  </Box>
                </Stack>
              )}
            </Stack>
          </Card>
        </Stack>
      </Box>

      <Card>
        <Stack spacing={2}>
          <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
            Candidate Edges
          </Typography>
          {!loading && data && data.edges.length === 0 ? (
            <EmptyState title="No Data Found" />
          ) : (
            <Box sx={{ minHeight: 420 }}>
              <DataGrid
                columns={edgeColumns}
                density="compact"
                disableRowSelectionOnClick
                getRowHeight={() => "auto"}
                getRowId={(row) => row.id}
                initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
                loading={loading}
                pageSizeOptions={[25, 50, 100]}
                rows={data?.edges || []}
                sx={{ "& .MuiDataGrid-cell": { alignItems: "flex-start", py: 1 } }}
              />
            </Box>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}
