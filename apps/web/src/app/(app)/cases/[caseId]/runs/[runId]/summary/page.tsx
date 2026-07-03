"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
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
  if (signal === "information") {
    return "neutral";
  }
  return "info";
}

type SummaryScope = "attention" | "all";

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
  const [summaryScope, setSummaryScope] = useState<SummaryScope>("attention");
  const [fallbackNotice, setFallbackNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(signal = goldenSignal, scope = summaryScope, allowFallback = true) {
    setLoading(true);
    setError(null);
    setFallbackNotice(null);
    try {
      const response = await reportsApi.summary(caseId, runId, {
        golden_signal: signal || undefined,
        scope,
        limit: 100,
      });
      if (
        allowFallback &&
        scope === "attention" &&
        !signal &&
        response.total === 0 &&
        (response.reduction.annotated_templates || 0) > 0
      ) {
        const fallbackResponse = await reportsApi.summary(caseId, runId, {
          scope: "all",
          limit: 100,
        });
        setSummaryScope("all");
        setFallbackNotice(
          "No attention templates were detected for this run, so all templates are shown.",
        );
        setData(fallbackResponse);
        return;
      }
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setGoldenSignal("");
    setSummaryScope("attention");
    void load("", "attention");
  }, [caseId, runId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load(goldenSignal, summaryScope);
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
            <InputLabel id="summary-scope-label">View</InputLabel>
            <Select
              inputProps={{ "aria-label": "View" }}
              label="View"
              labelId="summary-scope-label"
              native
              value={summaryScope}
              onChange={(event) => setSummaryScope(event.target.value as SummaryScope)}
            >
              <option value="attention">Attention templates</option>
              <option value="all">All templates</option>
            </Select>
          </FormControl>
          <FormControl sx={{ minWidth: 220 }}>
            <InputLabel id="summary-signal-label">Signal</InputLabel>
            <Select
              inputProps={{ "aria-label": "Signal" }}
              label="Signal"
              labelId="summary-signal-label"
              native
              value={goldenSignal}
              onChange={(event) => setGoldenSignal(event.target.value)}
            >
              <option value="">All signals</option>
              <option value="error">Error</option>
              <option value="availability">Availability</option>
              <option value="latency">Latency</option>
              <option value="saturation">Saturation</option>
              <option value="traffic">Traffic</option>
              <option value="information">Information</option>
              <option value="unknown">Unknown</option>
            </Select>
          </FormControl>
          <Button disabled={loading} type="submit" variant="secondary">
            Apply
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {fallbackNotice && <Alert severity="info">{fallbackNotice}</Alert>}
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(4, minmax(0, 1fr))" } }}>
        <Metric label="Raw lines" value={data ? String(data.reduction.raw_log_lines) : "n/a"} />
        <Metric label="Offending templates" value={data ? String(data.reduction.offending_templates) : "n/a"} />
        <Metric
          label="Visible templates"
          value={data ? String(data.reduction.visible_templates ?? data.total) : "n/a"}
        />
        <Metric
          label="Review reduction"
          value={data ? formatPercent(data.reduction.estimated_review_reduction) : "n/a"}
        />
      </Box>

      <Card>
        {!loading && data && data.items.length === 0 ? (
          <EmptyState title={summaryScope === "attention" && !goldenSignal ? "No attention templates found" : "No Data Found"}>
            <Typography color="text.secondary" variant="body2">
              {summaryScope === "attention" && !goldenSignal
                ? "This run did not produce error, availability, latency, saturation, or traffic templates. Switch to All templates to inspect informational and unknown patterns."
                : "No templates match the current view and signal filters."}
            </Typography>
          </EmptyState>
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
