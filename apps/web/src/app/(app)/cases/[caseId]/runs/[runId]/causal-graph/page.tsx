"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import cytoscape from "cytoscape";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { evidenceLogsHref } from "@/components/Evidence";
import Link from "@/components/Link";
import { SignalBadge } from "@/components/SignalBadge";
import { TemplateText } from "@/components/TemplateText";
import { Badge, Button, Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { CausalGraphResponse, CausalNode } from "@/lib/api";
import { apiErrorMessage, formatPercent } from "@/lib/format";
import { SIGNAL_ORDER, signalColor } from "@/lib/signals";
import { templateLabel } from "@/lib/templates";

const MAX_RENDERED_EDGES = 30;
const MIN_CONFIDENCE_OPTIONS = [0, 0.2, 0.35, 0.5, 0.7, 0.85];
const MAX_NODES_OPTIONS = [25, 50, 100, 200];

type GraphSelection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

/** Plain-text label for graph nodes and the edge summary; the API's `label` is the fallback. */
function nodeLabel(node: CausalNode | undefined, maxLength: number): string {
  if (!node) {
    return "unknown template";
  }
  return templateLabel(node.template_text ?? node.label, node.representative_message, maxLength);
}

function EdgeEndpoint({ node }: { node: CausalNode | undefined }) {
  if (!node) {
    return <>unknown template</>;
  }
  return (
    <TemplateText
      headline
      sample={node.representative_message}
      template={node.template_text ?? node.label}
      truncate
    />
  );
}

export default function CausalGraphPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const theme = useTheme();
  const graphElement = useRef<HTMLDivElement | null>(null);
  const graph = useRef<cytoscape.Core | null>(null);
  const [data, setData] = useState<CausalGraphResponse | null>(null);
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [error, setError] = useState<string | null>(null);
  const [minConfidence, setMinConfidence] = useState(0.35);
  const [maxNodes, setMaxNodes] = useState(100);

  useEffect(() => {
    let active = true;
    setData(null);
    setSelection(null);
    setError(null);
    reportsApi.causalGraph(caseId, runId, { max_nodes: maxNodes, min_confidence: minConfidence })
      .then((response) => {
        if (active) {
          setData(response);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(apiErrorMessage(caught));
        }
      });
    return () => {
      active = false;
    };
  }, [caseId, maxNodes, minConfidence, runId]);

  /** Logs around the node's representative line, or every line of its template. */
  function nodeLogsHref(node: CausalNode | undefined, templateId: string): string {
    const evidence = node?.evidence_refs[0];
    if (evidence) {
      return evidenceLogsHref(caseId, runId, evidence);
    }
    const params = new URLSearchParams({ template_id: templateId });
    return `/cases/${caseId}/runs/${runId}/logs?${params.toString()}`;
  }

  const nodesById = useMemo(
    () => new Map(data?.nodes.map((node) => [node.id, node]) ?? []),
    [data],
  );
  const legendSignals = useMemo(
    () => SIGNAL_ORDER.filter((signal) => data?.nodes.some((node) => node.golden_signal === signal)),
    [data],
  );
  const rootTemplateIds = useMemo(
    () => new Set(data?.root_cause_candidates.map((candidate) => candidate.template_id) ?? []),
    [data],
  );
  const renderedEdges = useMemo(() => {
    if (!data) {
      return [];
    }
    const nodeIds = new Set(data.nodes.map((node) => node.id));
    return data.edges
      .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
      .sort((left, right) => right.confidence - left.confidence)
      .slice(0, MAX_RENDERED_EDGES);
  }, [data]);
  const graphElements = useMemo<cytoscape.ElementDefinition[]>(() => {
    if (!data) {
      return [];
    }
    return [
      ...data.nodes.map((node) => ({
        classes: rootTemplateIds.has(node.template_id) ? "root-candidate" : "",
        data: {
          color: signalColor(node.golden_signal),
          confidence: node.confidence,
          id: node.id,
          label: nodeLabel(node, 42),
          rankScore: node.rank_score,
        },
      })),
      ...renderedEdges.map((edge) => ({
        classes: edge.needs_validation ? "needs-validation" : "",
        data: {
          confidence: edge.confidence,
          id: edge.id,
          source: edge.source,
          target: edge.target,
        },
      })),
    ];
  }, [data, renderedEdges, rootTemplateIds]);

  const selectedNode = useMemo(
    () => (
      selection?.kind === "node"
        ? data?.nodes.find((node) => node.id === selection.id) ?? null
        : null
    ),
    [data, selection],
  );
  const selectedEdge = useMemo(
    () => (
      selection?.kind === "edge"
        ? data?.edges.find((edge) => edge.id === selection.id) ?? null
        : null
    ),
    [data, selection],
  );

  useEffect(() => {
    if (!data || data.nodes.length === 0 || !graphElement.current) {
      graph.current?.destroy();
      graph.current = null;
      return;
    }

    const instance = cytoscape({
      container: graphElement.current,
      elements: graphElements,
      layout: {
        avoidOverlap: true,
        directed: true,
        name: "breadthfirst",
        padding: 36,
        spacingFactor: 1.25,
      },
      maxZoom: 2.5,
      minZoom: 0.35,
      selectionType: "single",
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "border-color": theme.palette.background.paper,
            "border-width": 2,
            color: theme.palette.text.primary,
            "font-size": 10,
            height: "mapData(rankScore, 0, 1, 38, 72)",
            label: "data(label)",
            "min-zoomed-font-size": 8,
            "text-background-color": theme.palette.background.paper,
            "text-background-opacity": 0.9,
            "text-background-padding": "3px",
            "text-margin-y": -8,
            "text-max-width": "120px",
            "text-valign": "top",
            "text-wrap": "wrap",
            width: "mapData(rankScore, 0, 1, 38, 72)",
          },
        },
        {
          selector: "node.root-candidate",
          style: {
            "border-color": theme.palette.error.main,
            "border-width": 5,
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": theme.palette.text.primary,
            "border-width": 5,
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "line-color": theme.palette.grey[400],
            "line-opacity": (edge: cytoscape.EdgeSingular) => {
              const confidence = Number(edge.data("confidence"));
              return Math.max(0.3, Math.min(0.95, confidence || 0.3));
            },
            "target-arrow-color": theme.palette.grey[400],
            "target-arrow-shape": "triangle",
            width: "mapData(confidence, 0, 1, 1.5, 6)",
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
            "line-color": theme.palette.primary.main,
            "line-opacity": 1,
            "target-arrow-color": theme.palette.primary.main,
            width: 6,
          },
        },
      ],
      wheelSensitivity: 0.25,
    });
    graph.current = instance;

    instance.on("tap", "node", (event) => {
      setSelection({ kind: "node", id: event.target.id() });
    });
    instance.on("tap", "edge", (event) => {
      setSelection({ kind: "edge", id: event.target.id() });
    });

    const resizeObserver = new ResizeObserver(() => {
      instance.resize();
      instance.fit(undefined, 36);
    });
    resizeObserver.observe(graphElement.current);
    instance.ready(() => instance.fit(undefined, 36));

    return () => {
      resizeObserver.disconnect();
      instance.destroy();
      if (graph.current === instance) {
        graph.current = null;
      }
    };
  }, [data, graphElements, theme]);

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          Causal Candidates
        </Typography>
        <Typography color="text.secondary">
          Arrows show time-ordered associations that still require validation.
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading causal candidates" /></Card>}
      {data && (
        <>
          <Box
            sx={{
              display: "grid",
              gap: 2,
              gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" },
            }}
          >
            {data.root_cause_candidates.map((candidate) => {
              const node = data.nodes.find(
                (item) => item.template_id === candidate.template_id,
              );
              return (
                <Card key={candidate.template_id}>
                  <Stack spacing={1}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
                      <Stack direction="row" spacing={1} sx={{ alignItems: "baseline", minWidth: 0 }}>
                        <Typography sx={{ flexShrink: 0, fontWeight: 850 }}>#{candidate.rank}</Typography>
                        <TemplateText
                          headline
                          sample={node?.representative_message}
                          template={node?.template_text ?? node?.label}
                        />
                      </Stack>
                      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexShrink: 0 }}>
                        <Badge>{Math.round(candidate.score * 100)}%</Badge>
                        <Button
                          component={Link}
                          href={nodeLogsHref(node, candidate.template_id)}
                          size="sm"
                          variant="secondary"
                        >
                          Logs
                        </Button>
                      </Stack>
                    </Stack>
                    <Typography color="text.secondary" variant="body2">
                      {candidate.reason}
                    </Typography>
                  </Stack>
                </Card>
              );
            })}
          </Box>

          <Card>
            {data.nodes.length === 0 ? (
              <EmptyState title="No causal graph nodes" />
            ) : (
              <Stack spacing={2}>
                <Stack
                  direction={{ xs: "column", md: "row" }}
                  spacing={1.5}
                  sx={{ alignItems: { md: "center" }, justifyContent: "space-between" }}
                >
                  <Box>
                    <Typography sx={{ fontWeight: 800 }}>
                      Directed relationship graph
                    </Typography>
                    <Typography color="text.secondary" variant="caption">
                      Node size = causal rank · red ring = root candidate · dashed edge = validate
                    </Typography>
                  </Box>
                  <Stack direction="row" spacing={1.5}>
                    <TextField
                      label="Min confidence"
                      select
                      size="small"
                      sx={{ minWidth: 150 }}
                      value={String(minConfidence)}
                      onChange={(event) => setMinConfidence(Number(event.target.value))}
                    >
                      {MIN_CONFIDENCE_OPTIONS.map((value) => (
                        <MenuItem key={value} value={String(value)}>
                          {Math.round(value * 100)}%
                        </MenuItem>
                      ))}
                    </TextField>
                    <TextField
                      label="Max nodes"
                      select
                      size="small"
                      sx={{ minWidth: 120 }}
                      value={String(maxNodes)}
                      onChange={(event) => setMaxNodes(Number(event.target.value))}
                    >
                      {MAX_NODES_OPTIONS.map((value) => (
                        <MenuItem key={value} value={String(value)}>
                          {value}
                        </MenuItem>
                      ))}
                    </TextField>
                  </Stack>
                </Stack>
                {legendSignals.length > 0 && (
                  <Stack direction="row" sx={{ alignItems: "center", flexWrap: "wrap", gap: 1 }}>
                    <Typography color="text.secondary" variant="caption">
                      Node colour = golden signal:
                    </Typography>
                    {legendSignals.map((signal) => (
                      <SignalBadge key={signal} signal={signal} />
                    ))}
                  </Stack>
                )}
                <Box
                  aria-label="Directed causal relationship graph"
                  ref={graphElement}
                  role="img"
                  sx={{
                    bgcolor: "rgba(91,92,246,0.035)",
                    borderRadius: 2,
                    height: { xs: 420, md: 560 },
                    width: "100%",
                  }}
                />
                {data.edges.length > renderedEdges.length && (
                  <Typography color="text.secondary" variant="caption">
                    Showing the strongest {renderedEdges.length} of {data.edges.length} edges.
                    The complete list remains available below.
                  </Typography>
                )}
              </Stack>
            )}
          </Card>

          {(selectedNode || selectedEdge) && (
            <Card tone="subtle">
              {selectedNode && (
                <Stack spacing={0.75}>
                  <TemplateText
                    headline
                    sample={selectedNode.representative_message}
                    template={selectedNode.template_text ?? selectedNode.label}
                  />
                  <Typography color="text.secondary" variant="body2">
                    Signal: {selectedNode.golden_signal} · occurrences:{" "}
                    {selectedNode.occurrence_count} · causal rank:{" "}
                    {formatPercent(selectedNode.rank_score)}
                  </Typography>
                  <Box>
                    <Button
                      component={Link}
                      href={nodeLogsHref(selectedNode, selectedNode.template_id)}
                      size="sm"
                      variant="secondary"
                    >
                      Open logs
                    </Button>
                  </Box>
                </Stack>
              )}
              {selectedEdge && (
                <Stack spacing={0.75}>
                  <Typography sx={{ fontWeight: 850 }}>
                    {nodeLabel(nodesById.get(selectedEdge.source), 60)}
                    {" → "}
                    {nodeLabel(nodesById.get(selectedEdge.target), 60)}
                  </Typography>
                  <Typography color="text.secondary" variant="body2">
                    Confidence: {formatPercent(selectedEdge.confidence)} · lag:{" "}
                    {selectedEdge.lag_seconds ?? 0}s · support: {selectedEdge.support_windows}
                  </Typography>
                </Stack>
              )}
            </Card>
          )}

          <Card>
            {data.edges.length === 0 ? (
              <EmptyState title="No supported associations" />
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Earlier signal</TableCell>
                      <TableCell>Later signal</TableCell>
                      <TableCell align="right">Lag</TableCell>
                      <TableCell align="right">Support</TableCell>
                      <TableCell align="right">Score</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.edges.map((edge) => (
                      <TableRow key={edge.id} hover>
                        <TableCell sx={{ maxWidth: 360 }}>
                          <Box
                            component={Link}
                            href={nodeLogsHref(nodesById.get(edge.source), edge.source_template_id)}
                            sx={{ color: "inherit", display: "block", textDecoration: "none", "&:hover": { color: "primary.dark" } }}
                          >
                            <EdgeEndpoint node={nodesById.get(edge.source)} />
                          </Box>
                        </TableCell>
                        <TableCell sx={{ maxWidth: 360 }}>
                          <Box
                            component={Link}
                            href={nodeLogsHref(nodesById.get(edge.target), edge.target_template_id)}
                            sx={{ color: "inherit", display: "block", textDecoration: "none", "&:hover": { color: "primary.dark" } }}
                          >
                            <EdgeEndpoint node={nodesById.get(edge.target)} />
                          </Box>
                        </TableCell>
                        <TableCell align="right">{edge.lag_seconds ?? 0}s</TableCell>
                        <TableCell align="right">{edge.support_windows}</TableCell>
                        <TableCell align="right">
                          {Math.round(edge.confidence * 100)}%
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Card>
        </>
      )}
    </Stack>
  );
}
