"use client";

import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import {
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { runsApi } from "@/lib/api";
import type { AnalysisRunResponse } from "@/lib/api";
import { apiErrorMessage, formatDateTime } from "@/lib/format";
import { describeRunModel } from "@/lib/inference";
import { Badge, Button, Card, statusTone } from "@/components/ui";

interface AnalysisRunVersionBarProps {
  caseId: string;
  runId: string;
}

function reportLabel(pathname: string, runId: string): string {
  const suffix = pathname.split(`/runs/${runId}`)[1] || "";
  if (suffix.startsWith("/summary")) {
    return "Summary";
  }
  if (suffix.startsWith("/temporal")) {
    return "Timeline";
  }
  if (suffix.startsWith("/logs")) {
    return "Logs";
  }
  if (suffix.startsWith("/causal-graph")) {
    return "Causal graph";
  }
  if (suffix.startsWith("/causal-summary")) {
    return "Causal summary";
  }
  return "Report";
}

function pathSuffix(pathname: string, runId: string): string {
  const token = `/runs/${runId}`;
  const index = pathname.indexOf(token);
  if (index < 0) {
    return "/summary";
  }
  return pathname.slice(index + token.length) || "/summary";
}

export function AnalysisRunVersionBar({ caseId, runId }: AnalysisRunVersionBarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [runs, setRuns] = useState<AnalysisRunResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadRuns() {
      setLoading(true);
      setError(null);
      try {
        const response = await runsApi.list(caseId);
        if (!active) {
          return;
        }
        setRuns(
          [...response.items].sort((left, right) => right.run_number - left.run_number),
        );
      } catch (caught) {
        if (active) {
          setError(apiErrorMessage(caught));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadRuns();
    return () => {
      active = false;
    };
  }, [caseId, runId]);

  const currentRun = useMemo(
    () => runs.find((run) => run.analysis_run_id === runId) || null,
    [runId, runs],
  );
  const latestRun = runs[0] || null;
  const isLatest = Boolean(
    currentRun && latestRun && currentRun.analysis_run_id === latestRun.analysis_run_id,
  );
  const viewLabel = reportLabel(pathname, runId);
  const currentPathSuffix = pathSuffix(pathname, runId);
  const selectedRunValue = currentRun?.analysis_run_id || "";

  function navigateToRun(targetRunId: string) {
    const queryString = searchParams.toString();
    router.push(
      `/cases/${caseId}/runs/${targetRunId}${currentPathSuffix}${queryString ? `?${queryString}` : ""}`,
    );
  }

  return (
    <Card tone="subtle">
      <Stack spacing={2}>
        <Stack
          direction={{ xs: "column", lg: "row" }}
          spacing={1.5}
          sx={{
            alignItems: { xs: "flex-start", lg: "center" },
            justifyContent: "space-between",
          }}
        >
          <Box>
            <Typography
              color="primary"
              sx={{
                display: "block",
                fontWeight: 850,
                letterSpacing: 0.5,
                mb: 0.5,
                textTransform: "uppercase",
              }}
              variant="caption"
            >
              Report version
            </Typography>
            <Typography component="h2" sx={{ fontWeight: 850 }} variant="h6">
              {currentRun
                ? `${viewLabel} · Run #${currentRun.run_number}`
                : `${viewLabel} · Version details`}
            </Typography>
            <Typography color="text.secondary" variant="body2">
              {currentRun
                ? isLatest
                  ? "You are viewing the latest analysis version for this case."
                  : "You are viewing an older analysis version. Latest available version: " +
                    `Run #${latestRun?.run_number}.`
                : loading
                  ? "Loading version details for this report."
                  : "This report run could not be matched to the case version list."}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
            {currentRun && <Badge tone="info">Run #{currentRun.run_number}</Badge>}
            {currentRun && (
              <Badge tone={statusTone(currentRun.status)}>{currentRun.status}</Badge>
            )}
            {currentRun && (
              <Badge tone={isLatest ? "success" : "warning"}>
                {isLatest ? "Latest" : "Historical"}
              </Badge>
            )}
            {runs.length > 1 && (
              <Badge tone="neutral">{runs.length} versions</Badge>
            )}
          </Stack>
        </Stack>

        <Box
          sx={{
            display: "grid",
            gap: 1.25,
            gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" },
          }}
        >
          <Box
            sx={{ bgcolor: "rgba(255,255,255,0.72)", borderRadius: "12px", p: 1.5 }}
          >
            <Typography color="text.secondary" variant="caption">
              Started
            </Typography>
            <Typography sx={{ fontWeight: 700 }} variant="body2">
              {currentRun
                ? formatDateTime(currentRun.started_at)
                : loading
                  ? "Loading…"
                  : "n/a"}
            </Typography>
          </Box>
          <Box
            sx={{ bgcolor: "rgba(255,255,255,0.72)", borderRadius: "12px", p: 1.5 }}
          >
            <Typography color="text.secondary" variant="caption">
              Completed
            </Typography>
            <Typography sx={{ fontWeight: 700 }} variant="body2">
              {currentRun
                ? formatDateTime(currentRun.completed_at)
                : loading
                  ? "Loading…"
                  : "n/a"}
            </Typography>
          </Box>
          <Box
            sx={{ bgcolor: "rgba(255,255,255,0.72)", borderRadius: "12px", p: 1.5 }}
          >
            <Typography color="text.secondary" variant="caption">
              Model
            </Typography>
            <Typography sx={{ fontWeight: 700 }} variant="body2">
              {currentRun
                ? describeRunModel(currentRun)
                : loading
                  ? "Loading…"
                  : "n/a"}
            </Typography>
          </Box>
        </Box>

        <Stack
          direction={{ xs: "column", lg: "row" }}
          spacing={1.5}
          sx={{
            alignItems: { xs: "stretch", lg: "center" },
            justifyContent: "space-between",
          }}
        >
          <Box>
            <Typography sx={{ fontWeight: 700 }} variant="body2">
              {runs.length > 1
                ? "Switch versions without leaving the current report tab."
                : "This case currently has a single analysis version."}
            </Typography>
            <Typography color="text.secondary" variant="caption">
              {error ? `Version list unavailable: ${error}` : `Run ID: ${runId}`}
            </Typography>
          </Box>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1.25}
            sx={{ minWidth: { lg: 340 } }}
          >
            <FormControl
              disabled={loading || runs.length === 0}
              size="small"
              sx={{ minWidth: { xs: "100%", sm: 240 } }}
            >
              <InputLabel id="analysis-version-select-label">Version</InputLabel>
              <Select
                label="Version"
                labelId="analysis-version-select-label"
                value={selectedRunValue}
                onChange={(event) => navigateToRun(String(event.target.value))}
              >
                {!currentRun && (
                  <MenuItem disabled value="">
                    {loading ? "Loading versions…" : "Current run unavailable"}
                  </MenuItem>
                )}
                {runs.map((run) => (
                  <MenuItem key={run.analysis_run_id} value={run.analysis_run_id}>
                    {`Run #${run.run_number} · ${run.status}${
                      run.analysis_run_id === latestRun?.analysis_run_id ? " · latest" : ""
                    }`}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {latestRun && !isLatest && (
              <Button
                variant="secondary"
                onClick={() => navigateToRun(latestRun.analysis_run_id)}
              >
                Open latest
              </Button>
            )}
          </Stack>
        </Stack>
      </Stack>
    </Card>
  );
}

