"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { LogItem, LogsResponse, reportsApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
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

export default function LogsPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [data, setData] = useState<LogsResponse | null>(null);
  const [keyword, setKeyword] = useState("");
  const [service, setService] = useState("");
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(
    nextKeyword = keyword,
    nextService = service,
    nextWindowStart = windowStart,
    nextWindowEnd = windowEnd,
  ) {
    setLoading(true);
    setError(null);
    try {
      const response = await reportsApi.logs(caseId, runId, {
        q: nextKeyword || undefined,
        service: nextService || undefined,
        window_start: nextWindowStart || undefined,
        window_end: nextWindowEnd || undefined,
        limit: 200,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const nextWindowStart = params.get("window_start") || "";
    const nextWindowEnd = params.get("window_end") || "";
    setWindowStart(nextWindowStart);
    setWindowEnd(nextWindowEnd);
    void load("", "", nextWindowStart, nextWindowEnd);
  }, [caseId, runId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  function clearWindowFilter() {
    setWindowStart("");
    setWindowEnd("");
    void load(keyword, service, "", "");
  }

  async function copyEvidenceRef(value: string) {
    try {
      await navigator.clipboard?.writeText(value);
    } catch {
      // Clipboard access can be unavailable in some browser contexts.
    }
  }

  const serviceOptions = useMemo(() => {
    const values = new Set<string>();
    if (service) {
      values.add(service);
    }
    for (const facet of data?.facets.service || []) {
      values.add(facet.value);
    }
    return Array.from(values).sort();
  }, [data, service]);

  const columns = useMemo<GridColDef<LogItem>[]>(
    () => [
      {
        field: "timestamp",
        headerName: "Time",
        minWidth: 170,
        renderCell: (params) => formatDateTime(params.row.timestamp),
      },
      {
        field: "level",
        headerName: "Level",
        minWidth: 100,
        renderCell: (params) => valueLabel(params.row.level),
      },
      {
        field: "service",
        headerName: "Service",
        minWidth: 150,
        renderCell: (params) => valueLabel(params.row.service),
      },
      {
        field: "evidence",
        headerName: "Evidence",
        minWidth: 220,
        sortable: false,
        renderCell: (params) => {
          const ref = `${params.row.file_path}:${params.row.line_number}`;
          return (
            <Stack spacing={0.75} sx={{ alignItems: "flex-start", py: 1 }}>
              <Box component="code" sx={{ overflowWrap: "anywhere", whiteSpace: "normal" }}>
                {ref}
              </Box>
              <Button size="sm" variant="ghost" onClick={() => void copyEvidenceRef(ref)}>
                Copy ref
              </Button>
            </Stack>
          );
        },
      },
      {
        field: "message",
        headerName: "Message",
        flex: 1.5,
        minWidth: 360,
        renderCell: (params) => (
          <Stack spacing={0.75} sx={{ alignItems: "flex-start", py: 1, whiteSpace: "normal", overflowWrap: "anywhere" }}>
            <Typography variant="body2">{params.row.message}</Typography>
            <Stack direction="row" sx={{ flexWrap: "wrap", gap: 0.75 }}>
              <Badge tone={signalTone(params.row.golden_signal)}>{params.row.golden_signal}</Badge>
              {params.row.fault_categories.map((category) => (
                <Badge key={category} tone="neutral">{category}</Badge>
              ))}
            </Stack>
          </Stack>
        ),
      },
    ],
    [],
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
          Tabular Logs
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ width: { xs: "100%", lg: "auto" } }}>
          <TextField
            label="Keyword"
            placeholder="Search redacted logs"
            sx={{ minWidth: { sm: 260 } }}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <FormControl sx={{ minWidth: 180 }}>
            <InputLabel id="logs-service-label">Service</InputLabel>
            <Select
              label="Service"
              labelId="logs-service-label"
              value={service}
              onChange={(event) => setService(event.target.value)}
            >
              <MenuItem value="">Any</MenuItem>
              {serviceOptions.map((value) => (
                <MenuItem key={value} value={value}>{value}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button disabled={loading} type="submit" variant="secondary">
            Apply
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {(windowStart || windowEnd) && (
        <Stack
          data-testid="logs-window-filter"
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          sx={{ alignItems: { xs: "flex-start", sm: "center" }, bgcolor: "background.paper", border: 1, borderColor: "divider", borderRadius: 2, justifyContent: "space-between", p: 2 }}
        >
          <Typography>
            Window filter: {windowStart ? formatDateTime(windowStart) : "start"} to{" "}
            {windowEnd ? formatDateTime(windowEnd) : "end"}
          </Typography>
          <Button variant="secondary" onClick={clearWindowFilter}>
            Clear window
          </Button>
        </Stack>
      )}
      <Card>
        {!loading && data && data.items.length === 0 ? (
          <EmptyState title="No logs found" />
        ) : (
          <Box sx={{ minHeight: 640 }}>
            <DataGrid
              columns={columns}
              density="compact"
              disableRowSelectionOnClick
              getRowHeight={() => "auto"}
              getRowId={(row) => row.log_id}
              initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
              loading={loading}
              pageSizeOptions={[50, 100, 200]}
              rows={data?.items || []}
              sx={{ "& .MuiDataGrid-cell": { alignItems: "flex-start", py: 1 } }}
            />
          </Box>
        )}
      </Card>
    </Stack>
  );
}
