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
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Metric } from "@/components/Shell";
import { Badge, Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { SummaryResponse } from "@/lib/api";
import { apiErrorMessage, formatDateTime } from "@/lib/format";

export default function SummaryPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [scope, setScope] = useState<"attention" | "all">("attention");
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    reportsApi.summary(caseId, runId, { scope, limit: 200 })
      .then(setData)
      .catch((caught) => setError(apiErrorMessage(caught)));
  }, [caseId, runId, scope]);

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between" }}>
        <Box>
          <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">Signal Summary</Typography>
          <Typography color="text.secondary">Templates ranked for incident review.</Typography>
        </Box>
        <TextField select label="Scope" size="small" value={scope} onChange={(event) => setScope(event.target.value as "attention" | "all")}>
          <MenuItem value="attention">Attention signals</MenuItem>
          <MenuItem value="all">All templates</MenuItem>
        </TextField>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading summary" /></Card>}
      {data && (
        <>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" } }}>
            <Metric label="Visible templates" value={String(data.total)} />
            <Metric label="Raw lines" value={String(data.reduction.raw_log_lines)} />
            <Metric label="Review reduction" value={`${Math.round(data.reduction.estimated_review_reduction * 100)}%`} />
          </Box>
          <Card>
            {data.items.length === 0 ? <EmptyState title="No matching templates" /> : (
              <TableContainer>
                <Table size="small">
                  <TableHead><TableRow>
                    <TableCell>Signal</TableCell>
                    <TableCell>Template</TableCell>
                    <TableCell align="right">Count</TableCell>
                    <TableCell>First seen</TableCell>
                    <TableCell align="right">Confidence</TableCell>
                  </TableRow></TableHead>
                  <TableBody>
                    {data.items.map((item) => (
                      <TableRow key={item.template_id} hover>
                        <TableCell><Badge>{item.golden_signal}</Badge></TableCell>
                        <TableCell>
                          <Typography sx={{ fontWeight: 700 }} variant="body2">{item.template_text}</Typography>
                          <Typography color="text.secondary" variant="caption">{item.services.join(", ") || "unknown service"}</Typography>
                        </TableCell>
                        <TableCell align="right">{item.occurrence_count}</TableCell>
                        <TableCell>{formatDateTime(item.first_seen)}</TableCell>
                        <TableCell align="right">{Math.round(item.confidence * 100)}%</TableCell>
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
