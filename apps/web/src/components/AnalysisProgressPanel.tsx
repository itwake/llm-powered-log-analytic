"use client";

import Box from "@mui/material/Box";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Link from "@/components/Link";
import { AnalysisRunResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, statusTone } from "@/components/ui";

const PIPELINE_STEPS = [
  ["ingest_paths", "Ingest"],
  ["merge_entries", "Merge"],
  ["preprocess_redact", "Redact"],
  ["template_extraction", "Template"],
  ["representative_sampling", "Sample"],
  ["ai_platform_annotation", "Annotate"],
  ["broadcast_annotations", "Broadcast"],
  ["temporal_aggregation", "Temporal"],
  ["causal_graph", "Graph"],
  ["causal_summary", "Summary"],
] as const;

const PROGRESS_METRICS = [
  ["files_processed", "Files"],
  ["raw_lines", "Raw lines"],
  ["templates", "Templates"],
  ["windows", "Windows"],
] as const;

type StepStatus = "pending" | "processing" | "completed" | "failed" | "cancelled" | "skipped";

interface StepProgress {
  status: StepStatus;
  error_message?: string;
}

function stepProgress(run: AnalysisRunResponse, stepName: string): StepProgress {
  const steps = run.progress.steps;
  if (steps && typeof steps === "object") {
    const value = (steps as Record<string, unknown>)[stepName];
    if (value && typeof value === "object") {
      const step = value as Record<string, unknown>;
      const status = step.status;
      return {
        status: typeof status === "string" ? status as StepStatus : "pending",
        error_message: typeof step.error_message === "string" ? step.error_message : undefined,
      };
    }
  }
  if (run.status === "cancelled") {
    return {status: "pending"};
  }
  if (run.current_step === stepName && run.status !== "completed") {
    return {status: "processing"};
  }
  return {status: "pending"};
}

function progressNumber(run: AnalysisRunResponse, key: string): number | null {
  const value = run.progress[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

interface AnalysisProgressPanelProps {
  caseId: string;
  run: AnalysisRunResponse | null;
  cancelling?: boolean;
  onCancel?: (run: AnalysisRunResponse) => void;
}

function terminalRunStatus(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function stepColor(status: StepStatus): string {
  if (status === "completed") {
    return "success.main";
  }
  if (status === "failed") {
    return "error.main";
  }
  if (status === "processing") {
    return "warning.main";
  }
  if (status === "cancelled") {
    return "info.main";
  }
  if (status === "skipped") {
    return "text.disabled";
  }
  return "divider";
}

export function AnalysisProgressPanel({
  caseId,
  run,
  cancelling = false,
  onCancel,
}: AnalysisProgressPanelProps) {
  if (!run) {
    return (
      <Card>
        <Stack spacing={2}>
          <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
            Analysis Progress
          </Typography>
          <EmptyState title="No active analysis run" />
        </Stack>
      </Card>
    );
  }

  const stepRows = PIPELINE_STEPS.map(([name, label]) => {
    const progress = stepProgress(run, name);
    return { name, label, ...progress };
  });
  const completedSteps = stepRows.filter((step) => step.status === "completed").length;
  const failed = run.status === "failed" || stepRows.some((step) => step.status === "failed");
  const cancelled = run.status === "cancelled";
  const completionPercent = failed
    ? Math.max(8, Math.round((completedSteps / PIPELINE_STEPS.length) * 100))
    : run.status === "completed"
      ? 100
      : Math.max(8, Math.round((completedSteps / PIPELINE_STEPS.length) * 100));
  const canCancel = !terminalRunStatus(run.status) && Boolean(onCancel);
  return (
    <Card>
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between" }}>
          <Box>
            <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
              Analysis Progress
            </Typography>
            <Typography color="text.secondary">
              Run #{run.run_number} - {run.current_step}
            </Typography>
          </Box>
          <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
            {canCancel && (
              <Button disabled={cancelling} size="sm" variant="danger" onClick={() => onCancel?.(run)}>
                {cancelling ? "Stopping" : "Terminate"}
              </Button>
            )}
            <Badge tone={statusTone(run.status)}>{run.status}</Badge>
          </Stack>
        </Stack>

        <LinearProgress
          aria-label="Analysis progress"
          color={failed ? "error" : cancelled ? "info" : "primary"}
          sx={{ borderRadius: "999px", height: 10 }}
          value={completionPercent}
          variant="determinate"
        />

        <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", sm: "repeat(4, minmax(0, 1fr))" } }}>
          {PROGRESS_METRICS.map(([key, label]) => {
            const value = progressNumber(run, key);
            return (
              <Box key={key} sx={{ border: 1, borderColor: "divider", borderRadius: "10px", p: 1.5 }}>
                <Typography color="text.secondary" variant="caption">
                  {label}
                </Typography>
                <Typography sx={{ fontWeight: 850 }}>{value === null ? "n/a" : formatCount(value)}</Typography>
              </Box>
            );
          })}
        </Box>

        <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", xl: "repeat(3, minmax(0, 1fr))" } }}>
          {stepRows.map((step) => (
            <Stack
              direction="row"
              key={step.name}
              spacing={1.25}
              sx={{ border: 1, borderColor: "divider", borderRadius: "10px", minWidth: 0, p: 1.25 }}
            >
              <Box sx={{ bgcolor: stepColor(step.status), borderRadius: "50%", height: 10, mt: 0.7, width: 10 }} />
              <Box sx={{ minWidth: 0 }}>
                <Typography noWrap sx={{ fontWeight: 800 }}>
                  {step.label}
                </Typography>
                <Typography color="text.secondary" variant="caption">
                  {step.status}
                </Typography>
                {step.error_message && (
                  <Typography color="error" sx={{ overflowWrap: "anywhere" }} variant="caption">
                    {step.error_message}
                  </Typography>
                )}
              </Box>
            </Stack>
          ))}
        </Box>

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between" }}>
          <Stack direction="row" sx={{ flexWrap: "wrap", gap: 2 }}>
            <Box>
              <Typography color="text.secondary" variant="caption">Started</Typography>
              <Typography sx={{ fontWeight: 750 }}>{formatDateTime(run.started_at)}</Typography>
            </Box>
            <Box>
              <Typography color="text.secondary" variant="caption">Completed</Typography>
              <Typography sx={{ fontWeight: 750 }}>{formatDateTime(run.completed_at)}</Typography>
            </Box>
          </Stack>
          {run.status === "completed" && (
            <Button component={Link} href={`/cases/${caseId}/runs/${run.analysis_run_id}/summary`} variant="secondary">
              Open report
            </Button>
          )}
        </Stack>
      </Stack>
    </Card>
  );
}
