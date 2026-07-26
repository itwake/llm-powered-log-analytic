"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { TemporalResponse } from "@/lib/api";
import { apiErrorMessage, formatDateTime } from "@/lib/format";

type TemporalGroup = "golden_signal" | "service" | "fault_category" | "template";

export default function TemporalPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [groupBy, setGroupBy] = useState<TemporalGroup>("golden_signal");
  const [data, setData] = useState<TemporalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setData(null);
    setError(null);
    reportsApi.temporal(caseId, runId, { group_by: groupBy })
      .then((response) => {
        if (active) setData(response);
      })
      .catch((caught) => {
        if (active) setError(apiErrorMessage(caught));
      });
    return () => {
      active = false;
    };
  }, [caseId, runId, groupBy]);

  const maxCount = useMemo(
    () => Math.max(1, ...(data?.series.flatMap((series) => series.points.map((point) => point.count)) || [1])),
    [data],
  );

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between" }}>
        <Box>
          <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">Temporal Activity</Typography>
          <Typography color="text.secondary">Counts grouped into analysis windows.</Typography>
        </Box>
        <TextField
          select
          label="Group by"
          size="small"
          value={groupBy}
          onChange={(event) => setGroupBy(event.target.value as TemporalGroup)}
        >
          <MenuItem value="golden_signal">Signal</MenuItem>
          <MenuItem value="service">Service</MenuItem>
          <MenuItem value="fault_category">Fault category</MenuItem>
          <MenuItem value="template">Template</MenuItem>
        </TextField>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading temporal activity" /></Card>}
      {data && data.series.length === 0 && <Card><EmptyState title="No temporal activity" /></Card>}
      {data?.series.map((series) => (
        <Card key={series.name}>
          <Stack spacing={1.25}>
            <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">{series.name}</Typography>
            {series.points.map((point) => (
              <Box key={point.window_start} sx={{ alignItems: "center", display: "grid", gap: 1.5, gridTemplateColumns: "170px minmax(80px, 1fr) 50px" }}>
                <Typography color="text.secondary" variant="caption">{formatDateTime(point.window_start)}</Typography>
                <Box sx={{ bgcolor: "rgba(91,92,246,0.08)", borderRadius: 999, height: 10, overflow: "hidden" }}>
                  <Box sx={{ bgcolor: "primary.main", height: "100%", width: `${Math.max(2, point.count / maxCount * 100)}%` }} />
                </Box>
                <Typography align="right" variant="body2">{point.count}</Typography>
              </Box>
            ))}
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}
