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
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { LogsResponse } from "@/lib/api";
import { apiErrorMessage, formatDateTime } from "@/lib/format";

export default function LogsPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [service, setService] = useState("");
  const [data, setData] = useState<LogsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setData(await reportsApi.logs(caseId, runId, {
        q: query || undefined,
        service: service || undefined,
        limit: 500,
        window_start: searchParams.get("window_start") || undefined,
        window_end: searchParams.get("window_end") || undefined,
      }));
    } catch (caught) {
      setError(apiErrorMessage(caught));
    }
  }

  useEffect(() => {
    void load();
  }, [caseId, runId]);

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">Logs</Typography>
        <Typography color="text.secondary">Search the redacted log lines in this run.</Typography>
      </Box>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
        <TextField fullWidth label="Search" size="small" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void load(); }} />
        <TextField label="Service" size="small" value={service} onChange={(event) => setService(event.target.value)} />
        <Button onClick={() => void load()}>Search</Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading logs" /></Card>}
      {data && (
        <Card>
          {data.items.length === 0 ? <EmptyState title="No matching logs" /> : (
            <TableContainer>
              <Table size="small">
                <TableHead><TableRow>
                  <TableCell>Time</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell>Signal</TableCell>
                  <TableCell>Message</TableCell>
                  <TableCell>Source</TableCell>
                </TableRow></TableHead>
                <TableBody>
                  {data.items.map((item) => (
                    <TableRow key={item.log_id} hover>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>{formatDateTime(item.timestamp)}</TableCell>
                      <TableCell>{item.service || "unknown"}</TableCell>
                      <TableCell><Badge>{item.golden_signal}</Badge></TableCell>
                      <TableCell sx={{ maxWidth: 640, overflowWrap: "anywhere" }}>{item.message}</TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>{item.file_path}:{item.line_number}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Card>
      )}
    </Stack>
  );
}
