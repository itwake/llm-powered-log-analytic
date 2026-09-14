import type { AnalysisRunResponse } from "@/lib/api";

const STEP_LABELS: Record<string, string> = {
  queued: "Queued",
  ingest_paths: "Ingesting files",
  merge_entries: "Merging entries",
  preprocess_redact: "Redacting",
  template_extraction: "Extracting templates",
  representative_sampling: "Sampling",
  heuristic_annotation: "Classifying",
  ai_platform_annotation: "Annotating with AI",
  broadcast_annotations: "Applying annotations",
  temporal_aggregation: "Building the timeline",
  causal_graph: "Building the causal graph",
  causal_summary: "Writing the summary",
  finalizing: "Preparing reports",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Human-readable name of a pipeline step or run state as stored in `current_step`. */
export function stepLabel(step: string | null | undefined): string {
  if (!step) {
    return "n/a";
  }
  return STEP_LABELS[step] ?? step.replace(/_/g, " ");
}

/** The newest run whose reports can be opened; callers pass runs newest first. */
export function latestCompletedRun(runs: AnalysisRunResponse[]): AnalysisRunResponse | null {
  return runs.find((run) => run.status === "completed") ?? null;
}

export interface AiOutcome {
  level: "failed" | "partial";
  title: string;
  detail: string;
}

function progressNumber(progress: Record<string, unknown>, key: string): number | null {
  const value = progress[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Whether a completed run that asked for an AI provider actually received its output. Model calls
 * fall back silently inside the pipeline: a template whose annotation call failed keeps its
 * rule-based classification, and a failed summary call yields the structured summary. The
 * pipeline records the counts and the summary source in the run's progress; this reads them back.
 */
export function aiOutcome(run: AnalysisRunResponse | null | undefined): AiOutcome | null {
  if (!run || run.status !== "completed" || run.model_provider === "none") {
    return null;
  }
  const progress = run.progress ?? {};
  if (progress.llm_enabled === false) {
    return {
      level: "failed",
      title: "The AI provider was not used",
      detail:
        "No model gateway was available for this run, so templates keep their rule-based " +
        "classification and the summary is built from structured evidence.",
    };
  }
  const succeeded = progressNumber(progress, "annotations");
  const total = progressNumber(progress, "annotation_templates_total");
  const budget = progressNumber(progress, "annotation_budget");
  const attempted = total === null ? null : budget === null ? total : Math.min(total, budget);
  const failures =
    attempted !== null && succeeded !== null ? Math.max(0, attempted - succeeded) : 0;
  const summaryFellBack = progress.summary_source === "structured";
  if (failures === 0 && !summaryFellBack) {
    return null;
  }
  if (attempted !== null && attempted > 0 && failures === attempted && summaryFellBack) {
    return {
      level: "failed",
      title: "AI did not contribute to this run",
      detail:
        `All ${attempted} template annotation calls failed and the summary fell back to ` +
        "structured evidence. Run Test connection on the provider, then start a new run.",
    };
  }
  const parts: string[] = [];
  if (failures > 0) {
    parts.push(
      `${failures} of ${attempted} template annotation calls failed; those templates keep ` +
        "their rule-based classification",
    );
  }
  if (summaryFellBack) {
    parts.push(
      "the summary fell back to structured evidence because the model reply was unavailable " +
        "or invalid",
    );
  }
  const detail = parts.join(", and ");
  return {
    level: "partial",
    title: "AI was only partly applied",
    detail: `${detail.charAt(0).toUpperCase()}${detail.slice(1)}.`,
  };
}
