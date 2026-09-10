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
import { ConfidenceExplainer, confidenceLabel, confidenceReason, formatConfidence } from "@/components/ConfidenceExplainer";
import Link from "@/components/Link";
import { Metric } from "@/components/Shell";
import { SignalBadge } from "@/components/SignalBadge";
import { Button, Card, EmptyState } from "@/components/ui";
import { ApiError, reportsApi } from "@/lib/api";
import type { SummaryResponse } from "@/lib/api";
import { apiErrorMessage, formatDateTime } from "@/lib/format";

interface ReportErrorState {
  message: string;
  status?: number;
}

export default function SummaryPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [scope, setScope] = useState<"attention" | "all">("attention");
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [error, setError] = useState<ReportErrorState | null>(null);

  useEffect(() => {
    let active = true;
    setData(null);
    setError(null);
    reportsApi.summary(caseId, runId, { scope, limit: 200 })
      .then((response) => {
        if (active) setData(response);
      })
      .catch((caught) => {
        if (active) {
          setError({
            message: apiErrorMessage(caught),
            status: caught instanceof ApiError ? caught.status : undefined,
          });
        }
      });
    return () => {
      active = false;
    };
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

      {error && (
        <Alert severity="error">
          <Stack spacing={1}>
            <Typography sx={{ fontWeight: 750 }}>{error.message}</Typography>
            {error.status === 404 && (
              <>
                <Typography variant="body2">
                  This report URL was found by the web app, but the API could not find the case/run
                  for your current session. The run may belong to another user, have been deleted,
                  or this browser may not be signed in to the same API data store.
                </Typography>
                <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
                  <Button component={Link} href={`/cases/${caseId}`} size="sm" variant="secondary">
                    Back to case
                  </Button>
                  <Button component={Link} href="/cases" size="sm" variant="secondary">
                    Browse cases
                  </Button>
                </Stack>
              </>
            )}
          </Stack>
        </Alert>
      )}
      {!data && !error && <Card><EmptyState title="Loading summary" /></Card>}
      {data && (
        <>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" } }}>
            <Metric label="Visible templates" value={String(data.total)} />
            <Metric label="Raw lines" value={String(data.reduction.raw_log_lines)} />
            <Metric label="Review reduction" value={`${Math.round(data.reduction.estimated_review_reduction * 100)}%`} />
          </Box>
          <ConfidenceExplainer variant="summary" />
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
                    <TableCell />
                  </TableRow></TableHead>
                  <TableBody>
                    {data.items.map((item) => (
                      <TableRow key={item.template_id} hover>
                        <TableCell><SignalBadge signal={item.golden_signal} /></TableCell>
                        <TableCell>
                          <Typography sx={{ fontWeight: 700 }} variant="body2">{item.template_text}</Typography>
                          <Typography color="text.secondary" variant="caption">{item.services.join(", ") || "unknown service"}</Typography>
                        </TableCell>
                        <TableCell align="right">{item.occurrence_count}</TableCell>
                        <TableCell>{formatDateTime(item.first_seen)}</TableCell>
                        <TableCell align="right">
                          <Typography sx={{ fontWeight: 800 }} variant="body2">
                            {formatConfidence(item.confidence)}
                          </Typography>
                          <Typography color="text.secondary" variant="caption">
                            {confidenceLabel(item.confidence)} · {confidenceReason(item.confidence)}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Button
                            component={Link}
                            href={`/cases/${caseId}/runs/${runId}/logs?template_id=${item.template_id}`}
                            size="sm"
                            variant="secondary"
                          >
                            Logs
                          </Button>
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
