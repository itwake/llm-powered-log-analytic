import Link from "next/link";
import { AnalysisRunResponse, JobEventResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

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
  ["representative_samples", "Samples"],
  ["annotated_templates", "Annotations"],
  ["windows", "Windows"],
  ["nodes", "Nodes"],
  ["edges", "Edges"],
] as const;

type StepStatus = "pending" | "processing" | "completed" | "failed";

function statusClass(status: string): string {
  if (status === "completed") {
    return "green";
  }
  if (status === "failed") {
    return "red";
  }
  if (status === "processing" || status === "queued") {
    return "amber";
  }
  return "blue";
}

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
}

export function AnalysisProgressPanel({caseId, run, events}: AnalysisProgressPanelProps) {
  if (!run) {
    return (
      <section className="panel progress-panel">
        <h2>Analysis Progress</h2>
        <div className="empty">No active analysis run</div>
      </section>
    );
  }

  const byStep = latestEventsByStep(events);
  const stepRows = PIPELINE_STEPS.map(([name, label]) => {
    const event = byStep.get(name);
    return {name, label, event, status: stepStatus(run, name, event)};
  });
  const completedSteps = stepRows.filter((step) => step.status === "completed").length;
  const failed = run.status === "failed" || stepRows.some((step) => step.status === "failed");
  const completionPercent = failed
    ? Math.max(8, Math.round((completedSteps / PIPELINE_STEPS.length) * 100))
    : run.status === "completed"
      ? 100
      : Math.max(8, Math.round((completedSteps / PIPELINE_STEPS.length) * 100));
  const recentEvents = [...events].slice(-6).reverse();

  return (
    <section className="panel progress-panel">
      <div className="progress-header">
        <div>
          <h2>Analysis Progress</h2>
          <p className="muted">
            Run #{run.run_number} - {run.current_step}
          </p>
        </div>
        <span className={`pill ${statusClass(run.status)}`}>{run.status}</span>
      </div>

      <div className="progress-track" aria-label="Analysis progress">
        <div
          className={`progress-fill ${failed ? "failed" : ""}`}
          style={{width: `${completionPercent}%`}}
        />
      </div>

      <div className="progress-metrics">
        {PROGRESS_METRICS.map(([key, label]) => {
          const value = progressNumber(run, key);
          return (
            <div className="progress-metric" key={key}>
              <span>{label}</span>
              <strong>{value === null ? "n/a" : formatCount(value)}</strong>
            </div>
          );
        })}
      </div>

      <div className="step-timeline">
        {stepRows.map((step) => (
          <div className={`step-item ${step.status}`} key={step.name}>
            <span className="step-dot" />
            <div>
              <strong>{step.label}</strong>
              <span>{step.status}</span>
              {step.event?.metadata && Object.keys(step.event.metadata).length > 0 && (
                <small>{metadataPreview(step.event.metadata)}</small>
              )}
              {step.event?.error_message && <small>{step.event.error_message}</small>}
            </div>
          </div>
        ))}
      </div>

      <div className="progress-footer">
        <div>
          <span className="muted">Started</span>
          <strong>{formatDateTime(run.started_at)}</strong>
        </div>
        <div>
          <span className="muted">Completed</span>
          <strong>{formatDateTime(run.completed_at)}</strong>
        </div>
        {run.status === "completed" && (
          <Link className="button secondary" href={`/cases/${caseId}/runs/${run.analysis_run_id}/summary`}>
            Open report
          </Link>
        )}
      </div>

      {recentEvents.length > 0 && (
        <div className="event-log">
          <h3>Recent Events</h3>
          {recentEvents.map((event) => (
            <div className="event-row" key={event.id}>
              <span className={`pill ${statusClass(event.status)}`}>{event.event_type}</span>
              <span>{event.step_name}</span>
              <span className="muted">{formatDateTime(event.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
