"use client";

import Box from "@mui/material/Box";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useEffect, useRef } from "react";
import Link from "@/components/Link";
import { AnalysisRunResponse, JobEventResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, statusTone } from "@/components/ui";

const PIPELINE_STEPS = [
  ["ingest_paths", "Ingest"],
  ["merge_entries", "Merge"],
  ["preprocess_redact", "Redact"],
  ["drain_templating", "Template"],
  ["representative_sampling", "Sample"],
  ["ai_platform_annotation", "Annotate"],
  ["broadcast_annotations", "Broadcast"],
  ["temporal_aggregation", "Temporal"],
  ["causal_graph", "Graph"],
  ["causal_summary", "Summary"],
  ["export_artifacts", "Export"],
] as const;

const PROGRESS_METRICS = [
  ["files_processed", "Files"],
  ["raw_lines", "Raw lines"],
  ["templates", "Templates"],
  ["windows", "Windows"],
] as const;

type StepStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

function latestEventsByStep(events: JobEventResponse[]): Map<string, JobEventResponse> {
  const byStep = new Map<string, JobEventResponse>();
  for (const event of events) {
    byStep.set(event.step_name, event);
  }
  return byStep;
}

function stepStatus(
  run: AnalysisRunResponse,
  stepName: string,
  latestEvent: JobEventResponse | undefined,
): StepStatus {
  if (latestEvent?.status === "failed" || latestEvent?.event_type === "failed") {
    return "failed";
  }
  if (latestEvent?.status === "completed" || latestEvent?.event_type === "completed") {
    return "completed";
  }
  if (latestEvent?.status === "cancelled" || latestEvent?.event_type === "cancelled") {
    return "cancelled";
  }
  if (run.status === "cancelled") {
    return "pending";
  }
  if (latestEvent?.status === "processing" || latestEvent?.event_type === "started") {
    return "processing";
  }
  if (run.current_step === stepName && run.status !== "completed") {
    return "processing";
  }
  return "pending";
}

function progressNumber(run: AnalysisRunResponse, key: string): number | null {
  const value = run.progress[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function metadataPreview(metadata: Record<string, unknown>): string {
  const entries = Object.entries(metadata).filter(([, value]) =>
    typeof value === "number" || typeof value === "string" || typeof value === "boolean",
  );
  return entries.slice(0, 3).map(([key, value]) => `${key}: ${String(value)}`).join(" - ");
}

interface AnalysisProgressPanelProps {
  caseId: string;
  run: AnalysisRunResponse | null;
  events: JobEventResponse[];
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
  return "divider";
}

export function AnalysisProgressPanel({
  caseId,
  run,
  events,
  cancelling = false,
  onCancel,
}: AnalysisProgressPanelProps) {
  const eventLogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (eventLogRef.current) {
      eventLogRef.current.scrollTop = eventLogRef.current.scrollHeight;
    }
  }, [events.length, run?.analysis_run_id]);

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

  const byStep = latestEventsByStep(events);
  const stepRows = PIPELINE_STEPS.map(([name, label]) => {
    const event = byStep.get(name);
    return { name, label, event, status: stepStatus(run, name, event) };
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
  const visibleEvents = events.slice(-16);

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
                {step.event?.metadata && Object.keys(step.event.metadata).length > 0 && (
                  <Typography color="text.secondary" sx={{ overflowWrap: "anywhere" }} variant="caption">
                    {metadataPreview(step.event.metadata)}
                  </Typography>
                )}
                {step.event?.error_message && (
                  <Typography color="error" sx={{ overflowWrap: "anywhere" }} variant="caption">
                    {step.event.error_message}
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

        {events.length > 0 && (
          <Box>
            <Typography component="h3" gutterBottom sx={{ fontWeight: 800 }} variant="subtitle1">
              Event Log
            </Typography>
            <Stack
              ref={eventLogRef}
              spacing={1}
              sx={{
                border: 1,
                borderColor: "divider",
                borderRadius: "10px",
                maxHeight: 320,
                overflowY: "auto",
                p: 1,
              }}
            >
              {visibleEvents.map((event) => (
                <Stack direction="row" key={event.id} spacing={1} sx={{ alignItems: "flex-start", minWidth: 0 }}>
                  <Badge tone={statusTone(event.status)}>{event.event_type}</Badge>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 750, overflowWrap: "anywhere" }} variant="body2">
                      {event.step_name}
                    </Typography>
                    {event.metadata && Object.keys(event.metadata).length > 0 && (
                      <Typography color="text.secondary" sx={{ overflowWrap: "anywhere" }} variant="caption">
                        {metadataPreview(event.metadata)}
                      </Typography>
                    )}
                    {event.error_message && (
                      <Typography color="error" sx={{ overflowWrap: "anywhere" }} variant="caption">
                        {event.error_message}
                      </Typography>
                    )}
                  </Box>
                  <Typography color="text.secondary" sx={{ flex: "0 0 auto" }} variant="caption">
                    {formatDateTime(event.created_at)}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </Box>
        )}
      </Stack>
    </Card>
  );
}
