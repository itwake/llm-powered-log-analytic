from __future__ import annotations

import json
import re

from logan_workers.evaluation.schemas import BenchmarkEvaluationReport, MetricScore


SENSITIVE_TERM_RE = re.compile(
    r"\b(authorization|bearer|password|passwd|secret|token|access[_-]?token|api[_-]?key)\b",
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:/(?:root|home|tmp|var|etc|workspace|Users)/[^\s\"']+|[A-Za-z]:\\[^\s\"']+)"
)
RAW_FIELD_RE = re.compile(
    r"\b("
    r"raw_message|raw_text|raw_line_ids|raw_line_id|raw_model_response|"
    r"model_inputs|representative_lines|template_text|normalized_message|"
    r"redacted_message|object_uri|file_path|original_filename"
    r")\b",
    re.IGNORECASE,
)


def find_unsafe_report_terms(text: str) -> list[str]:
    issues: list[str] = []
    if SENSITIVE_TERM_RE.search(text):
        issues.append("sensitive_term")
    if ABSOLUTE_PATH_RE.search(text):
        issues.append("absolute_path")
    if RAW_FIELD_RE.search(text):
        issues.append("raw_or_prompt_field")
    return issues


def ensure_report_text_is_safe(text: str) -> None:
    issues = find_unsafe_report_terms(text)
    if issues:
        issue_list = ", ".join(sorted(set(issues)))
        raise ValueError(f"evaluation report contains unsafe content categories: {issue_list}")


def report_to_json(report: BenchmarkEvaluationReport) -> str:
    text = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)
    ensure_report_text_is_safe(text)
    return text


def _format_score(metric: MetricScore) -> str:
    value = f"{metric.value:.4f}"
    if metric.threshold is None:
        return value
    status = "pass" if metric.passed else "fail"
    return f"{value} (min {metric.threshold:.4f}, {status})"


def report_to_markdown(report: BenchmarkEvaluationReport) -> str:
    lines = [
        "# LogAn Benchmark Evaluation",
        "",
        f"Benchmark: `{report.benchmark_id}`",
        f"Case: `{report.case_id}`",
        f"Analysis run: `{report.analysis_run_id}`",
        f"Status: `{report.status}`",
        "",
        "## Metrics",
        "",
        "| Metric | Score |",
        "| --- | ---: |",
    ]
    for name, metric in sorted(report.metrics.items()):
        lines.append(f"| `{name}` | {_format_score(metric)} |")

    lines.extend(
        [
            "",
            "## Pipeline Counts",
            "",
            "| Count | Value |",
            "| --- | ---: |",
            f"| Source entries | {report.pipeline_counts.raw_entries} |",
            f"| Normalized logs | {report.pipeline_counts.normalized_logs} |",
            f"| Templates | {report.pipeline_counts.templates} |",
            f"| Representative samples | {report.pipeline_counts.samples} |",
            f"| Annotations | {report.pipeline_counts.annotations} |",
            f"| Causal nodes | {report.pipeline_counts.causal_nodes} |",
            f"| Causal edges | {report.pipeline_counts.causal_edges} |",
            "",
            "## Expected Templates",
            "",
            "| Label | Matched | Expected signal | Actual signal |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in report.template_patterns:
        actual = item.actual_golden_signal or ""
        lines.append(
            f"| `{item.label_id}` | `{str(item.matched).lower()}` | "
            f"`{item.expected_golden_signal}` | `{actual}` |"
        )

    lines.extend(
        [
            "",
            "## Useful Causal Edges",
            "",
            "| Label | Matched | Confidence | Method |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for edge in report.useful_causal_edges:
        confidence = "" if edge.confidence is None else f"{edge.confidence:.4f}"
        method = edge.method or ""
        lines.append(
            f"| `{edge.label_id}` | `{str(edge.matched).lower()}` | "
            f"{confidence} | `{method}` |"
        )

    lines.extend(
        [
            "",
            "## Root Cause",
            "",
            f"Top-k: `{report.root_cause.top_k}`",
            f"Hit: `{str(report.root_cause.hit).lower()}`",
        ]
    )
    if report.root_cause.hit_rank is not None:
        lines.append(f"Hit rank: `{report.root_cause.hit_rank}`")

    lines.extend(
        [
            "",
            "## Summary Rubric",
            "",
            "| Item | Score | Missing terms |",
            "| --- | ---: | --- |",
        ]
    )
    for item in report.summary_rubric:
        missing = ", ".join(item.missing_terms)
        lines.append(f"| `{item.key}` | {item.score:.4f} | `{missing}` |")

    text = "\n".join(lines) + "\n"
    ensure_report_text_is_safe(text)
    return text
