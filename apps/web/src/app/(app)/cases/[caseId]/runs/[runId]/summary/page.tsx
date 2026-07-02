"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "@/components/Link";
import { reportsApi, SummaryResponse } from "@/lib/api";
import type { SummaryItem } from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatPercent, valueLabel } from "@/lib/format";
import { Metric } from "@/components/Shell";
import { Badge, Button, Card, EmptyState } from "@/components/ui";

function signalTone(signal: string) {
  if (signal === "error") {
    return "danger";
  }
  if (signal === "availability" || signal === "saturation") {
    return "warning";
  }
  return "info";
}

function summaryLogsHref(caseId: string, runId: string, item: SummaryItem): string {
  const basePath = `/cases/${caseId}/runs/${runId}/logs`;
  const firstSeen = item.first_seen ? new Date(item.first_seen) : null;
  const lastSeen = item.last_seen ? new Date(item.last_seen) : null;
  if (firstSeen && lastSeen && !Number.isNaN(firstSeen.getTime()) && !Number.isNaN(lastSeen.getTime())) {
    const params = new URLSearchParams({
      window_start: new Date(firstSeen.getTime() - 60_000).toISOString(),
      window_end: new Date(lastSeen.getTime() + 60_000).toISOString(),
    });
    return `${basePath}?${params.toString()}`;
  }
  if (item.template_id) {
    const params = new URLSearchParams({ q: item.template_id });
    return `${basePath}?${params.toString()}`;
  }
  return basePath;
}

export default function SummaryPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [goldenSignal, setGoldenSignal] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(signal = goldenSignal) {
    setLoading(true);
    setError(null);
    try {
      const response = await reportsApi.summary(caseId, runId, {
        golden_signal: signal || undefined,
        limit: 100,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("");
  }, [caseId, runId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  const columns = useMemo<GridColDef<SummaryItem>[]>(
    () => [
      {
        field: "golden_signal",
        headerName: "Signal",
        minWidth: 130,
        renderCell: (params) => <Badge tone={signalTone(params.row.golden_signal)}>{params.row.golden_signal}</Badge>,
      },
      {
        field: "representative_message",
        headerName: "Representative log",
        flex: 1.6,
        minWidth: 320,
        renderCell: (params) => (
          <Box sx={{ py: 1, whiteSpace: "normal", overflowWrap: "anywhere" }}>
            <Typography variant="body2">{params.row.representative_message}</Typography>
            <Typography color="text.secondary" variant="caption">
              {params.row.fault_categories.join(", ") || "uncategorized"}
            </Typography>
          </Box>
        ),
      },
      { field: "occurrence_count", headerName: "Count", minWidth: 100, type: "number" },
      {
        field: "services",
        headerName: "Service",
        flex: 0.8,
        minWidth: 160,
        renderCell: (params) => (
          <Typography sx={{ whiteSpace: "normal", overflowWrap: "anywhere" }} variant="body2">
            {params.row.services.map(valueLabel).join(", ")}
          </Typography>
        ),
      },
      {
        field: "first_seen",
        headerName: "First seen",
        minWidth: 170,
        renderCell: (params) => formatDateTime(params.row.first_seen),
      },
      {
        field: "confidence",
        headerName: "Confidence",
        minWidth: 120,
        renderCell: (params) => formatPercent(params.row.confidence),
      },
      {
        field: "evidence",
        headerName: "Evidence",
        minWidth: 130,
        sortable: false,
        renderCell: (params) => (
          <Button component={Link} href={summaryLogsHref(caseId, runId, params.row)} size="sm" variant="secondary">
            Open logs
          </Button>
        ),
      },
    ],
    [caseId, runId],
  );

  return (
    <Stack spacing={2.5}>
      <Stack
        component="form"
        direction={{ xs: "column", md: "row" }}
        spacing={2}
        sx={{ alignItems: { xs: "flex-start", md: "center" }, justifyContent: "space-between" }}
        onSubmit={submit}
      >
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          Data Summary
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ width: { xs: "100%", md: "auto" } }}>
          <FormControl sx={{ minWidth: 220 }}>
            <InputLabel id="summary-signal-label">Signal</InputLabel>
            <Select
              label="Signal"
              labelId="summary-signal-label"
              value={goldenSignal}
              onChange={(event) => setGoldenSignal(event.target.value)}
            >
              <MenuItem value="">All offending</MenuItem>
              <MenuItem value="error">Error</MenuItem>
              <MenuItem value="availability">Availability</MenuItem>
              <MenuItem value="latency">Latency</MenuItem>
              <MenuItem value="saturation">Saturation</MenuItem>
              <MenuItem value="traffic">Traffic</MenuItem>
            </Select>
          </FormControl>
          <Button disabled={loading} type="submit" variant="secondary">
            Apply
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" } }}>
        <Metric label="Raw lines" value={data ? String(data.reduction.raw_log_lines) : "n/a"} />
        <Metric label="Offending templates" value={data ? String(data.reduction.offending_templates) : "n/a"} />
        <Metric
          label="Review reduction"
          value={data ? formatPercent(data.reduction.estimated_review_reduction) : "n/a"}
        />
      </Box>

      <Card>
        {!loading && data && data.items.length === 0 ? (
          <EmptyState title="No summary rows" />
        ) : (
          <Box sx={{ minHeight: 520 }}>
            <DataGrid
              columns={columns}
              density="compact"
              disableRowSelectionOnClick
              getRowHeight={() => "auto"}
              getRowId={(row) => row.template_id}
              initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
              loading={loading}
              pageSizeOptions={[25, 50, 100]}
              rows={data?.items || []}
              sx={{
                "& .MuiDataGrid-cell": { alignItems: "flex-start", py: 1 },
              }}
            />
          </Box>
        )}
      </Card>
    </Stack>
  );
}
