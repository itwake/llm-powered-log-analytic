from __future__ import annotations

from prometheus_client import Counter, Histogram

PIPELINE_STEP_NAMES = frozenset(
    {
        "ingest_paths",
        "merge_entries",
        "preprocess_redact",
        "drain_templating",
        "representative_sampling",
        "ai_platform_annotation",
        "broadcast_annotations",
        "temporal_aggregation",
        "causal_graph",
        "causal_summary",
        "export_artifacts",
    }
)

_PIPELINE_RUNS_TOTAL = Counter(
    "logan_pipeline_runs_total",
    "Analysis pipeline runs by terminal status.",
    ("status",),
)
_PIPELINE_STEPS_TOTAL = Counter(
    "logan_pipeline_steps_total",
    "Analysis pipeline step events by status.",
    ("step_name", "status"),
)
_PIPELINE_STEP_DURATION_SECONDS = Histogram(
    "logan_pipeline_step_duration_seconds",
    "Analysis pipeline step duration in seconds.",
    ("step_name", "status"),
)


def record_pipeline_run_started() -> None:
    _PIPELINE_RUNS_TOTAL.labels(status="started").inc()


def record_pipeline_run_completed() -> None:
    _PIPELINE_RUNS_TOTAL.labels(status="completed").inc()


def record_pipeline_run_failed() -> None:
    _PIPELINE_RUNS_TOTAL.labels(status="failed").inc()


def record_pipeline_step_started(step_name: str) -> None:
    _PIPELINE_STEPS_TOTAL.labels(
        step_name=_pipeline_step_label(step_name),
        status="started",
    ).inc()


def record_pipeline_step_completed(step_name: str, duration_seconds: float) -> None:
    step_label = _pipeline_step_label(step_name)
    _PIPELINE_STEPS_TOTAL.labels(step_name=step_label, status="completed").inc()
    _PIPELINE_STEP_DURATION_SECONDS.labels(
        step_name=step_label,
        status="completed",
    ).observe(max(0.0, duration_seconds))


def record_pipeline_step_failed(step_name: str, duration_seconds: float) -> None:
    step_label = _pipeline_step_label(step_name)
    _PIPELINE_STEPS_TOTAL.labels(step_name=step_label, status="failed").inc()
    _PIPELINE_STEP_DURATION_SECONDS.labels(
        step_name=step_label,
        status="failed",
    ).observe(max(0.0, duration_seconds))


def _pipeline_step_label(step_name: str) -> str:
    return step_name if step_name in PIPELINE_STEP_NAMES else "unknown"
