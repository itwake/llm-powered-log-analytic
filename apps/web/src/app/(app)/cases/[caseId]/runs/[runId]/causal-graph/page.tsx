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
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { CausalGraphResponse } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";

export default function CausalGraphPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [data, setData] = useState<CausalGraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    reportsApi.causalGraph(caseId, runId, { max_nodes: 100, min_confidence: 0.35 })
      .then(setData)
      .catch((caught) => setError(apiErrorMessage(caught)));
  }, [caseId, runId]);

  const labels = new Map(data?.nodes.map((node) => [node.id, node.label]) || []);

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">Causal Candidates</Typography>
        <Typography color="text.secondary">
          Time-ordered associations that need validation with metrics and traces.
        </Typography>
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading causal candidates" /></Card>}
      {data && (
        <>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" } }}>
            {data.root_cause_candidates.map((candidate) => {
              const node = data.nodes.find((item) => item.template_id === candidate.template_id);
              return (
                <Card key={candidate.template_id}>
                  <Stack spacing={1}>
                    <Stack direction="row" sx={{ justifyContent: "space-between" }}>
                      <Typography sx={{ fontWeight: 850 }}>#{candidate.rank} {node?.label || candidate.template_id}</Typography>
                      <Badge>{Math.round(candidate.score * 100)}%</Badge>
                    </Stack>
                    <Typography color="text.secondary" variant="body2">{candidate.reason}</Typography>
                  </Stack>
                </Card>
              );
            })}
          </Box>
          <Card>
            {data.edges.length === 0 ? <EmptyState title="No supported associations" /> : (
              <TableContainer>
                <Table size="small">
                  <TableHead><TableRow>
                    <TableCell>Earlier signal</TableCell>
                    <TableCell>Later signal</TableCell>
                    <TableCell align="right">Lag</TableCell>
                    <TableCell align="right">Support</TableCell>
                    <TableCell align="right">Score</TableCell>
                  </TableRow></TableHead>
                  <TableBody>
                    {data.edges.map((edge) => (
                      <TableRow key={edge.id} hover>
                        <TableCell>{labels.get(edge.source) || edge.source}</TableCell>
                        <TableCell>{labels.get(edge.target) || edge.target}</TableCell>
                        <TableCell align="right">{edge.lag_seconds ?? 0}s</TableCell>
                        <TableCell align="right">{edge.support_windows}</TableCell>
                        <TableCell align="right">{Math.round(edge.confidence * 100)}%</TableCell>
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
