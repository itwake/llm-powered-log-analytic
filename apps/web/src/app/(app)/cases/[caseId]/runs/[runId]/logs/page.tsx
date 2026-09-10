"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { LogTable } from "@/components/LogTable";
import { Button, Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { LogsResponse } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";

export default function LogsPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") || "";
  const windowStart = searchParams.get("window_start") || undefined;
  const windowEnd = searchParams.get("window_end") || undefined;
  const [templateId, setTemplateId] = useState(searchParams.get("template_id") || "");
  const [query, setQuery] = useState(initialQuery);
  const [data, setData] = useState<LogsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const load = useCallback(async (nextQuery: string, nextTemplateId?: string) => {
    const currentRequest = ++requestId.current;
    setError(null);
    try {
      const response = await reportsApi.logs(caseId, runId, {
        q: nextQuery || undefined,
        template_id: nextTemplateId || undefined,
        limit: 500,
        window_start: windowStart,
        window_end: windowEnd,
      });
      if (requestId.current === currentRequest) {
        setData(response);
      }
    } catch (caught) {
      if (requestId.current === currentRequest) {
        setError(apiErrorMessage(caught));
      }
    }
  }, [caseId, runId, windowEnd, windowStart]);

  useEffect(() => {
    void load(initialQuery, templateId);
    return () => {
      requestId.current += 1;
    };
    // templateId is intentionally read once from the URL for the initial load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery, load]);

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">Logs</Typography>
        <Typography color="text.secondary">Search the redacted log lines in this run.</Typography>
      </Box>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
        <TextField fullWidth label="Search" size="small" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void load(query, templateId); }} />
        <Button onClick={() => void load(query, templateId)}>Search</Button>
      </Stack>
      {templateId && (
        <Alert
          onClose={() => {
            setTemplateId("");
            void load(query, "");
          }}
          severity="info"
        >
          Filtered to one template ({templateId.slice(0, 8)}…). Close to see all logs.
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading logs" /></Card>}
      {data && (
        <Card>
          <LogTable items={data.items} />
        </Card>
      )}
    </Stack>
  );
}
