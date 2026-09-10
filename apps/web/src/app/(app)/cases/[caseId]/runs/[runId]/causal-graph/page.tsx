"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import cytoscape from "cytoscape";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { CausalGraphResponse } from "@/lib/api";
import { apiErrorMessage, formatPercent } from "@/lib/format";
import { cleanTemplateLabel, signalColor } from "@/lib/signals";

const MAX_RENDERED_EDGES = 30;

type GraphSelection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

export default function CausalGraphPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const theme = useTheme();
  const graphElement = useRef<HTMLDivElement | null>(null);
  const graph = useRef<cytoscape.Core | null>(null);
  const [data, setData] = useState<CausalGraphResponse | null>(null);
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setData(null);
    setSelection(null);
    setError(null);
    reportsApi.causalGraph(caseId, runId, { max_nodes: 100, min_confidence: 0.35 })
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
  }, [caseId, runId]);

  const labels = useMemo(
    () => new Map(data?.nodes.map((node) => [node.id, node.label]) ?? []),
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
          label: cleanTemplateLabel(node.label, 42),
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
                    <Stack direction="row" sx={{ justifyContent: "space-between" }}>
                      <Typography sx={{ fontWeight: 850 }}>
                        #{candidate.rank} {cleanTemplateLabel(node?.label, 80)}
                      </Typography>
                      <Badge>{Math.round(candidate.score * 100)}%</Badge>
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
                  direction={{ xs: "column", sm: "row" }}
                  spacing={1}
                  sx={{ justifyContent: "space-between" }}
                >
                  <Typography sx={{ fontWeight: 800 }}>
                    Directed relationship graph
                  </Typography>
                  <Typography color="text.secondary" variant="caption">
                    Node size = causal rank · red ring = root candidate · dashed edge = validate
                  </Typography>
                </Stack>
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
                  <Typography sx={{ fontWeight: 850 }}>
                    {cleanTemplateLabel(selectedNode.label, 120)}
                  </Typography>
                  <Typography color="text.secondary" variant="body2">
                    Signal: {selectedNode.golden_signal} · occurrences:{" "}
                    {selectedNode.occurrence_count} · causal rank:{" "}
                    {formatPercent(selectedNode.rank_score)}
                  </Typography>
                </Stack>
              )}
              {selectedEdge && (
                <Stack spacing={0.75}>
                  <Typography sx={{ fontWeight: 850 }}>
                    {cleanTemplateLabel(labels.get(selectedEdge.source), 60)}
                    {" → "}
                    {cleanTemplateLabel(labels.get(selectedEdge.target), 60)}
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
                        <TableCell>{labels.get(edge.source) || edge.source}</TableCell>
                        <TableCell>{labels.get(edge.target) || edge.target}</TableCell>
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
