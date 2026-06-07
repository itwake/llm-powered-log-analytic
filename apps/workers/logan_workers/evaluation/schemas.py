from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from logan_workers.models import GoldenSignal


def _validate_regex(value: str) -> str:
    try:
        re.compile(value)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc
    return value


class ExpectedTemplateLabel(BaseModel):
    id: str = Field(min_length=1)
    template_pattern: str = Field(min_length=1)
    golden_signal: GoldenSignal
    fault_categories: list[str] = Field(default_factory=list)
    entities: dict[str, list[str]] = Field(default_factory=dict)
    offending: bool = True

    @field_validator("template_pattern")
    @classmethod
    def validate_template_pattern(cls, value: str) -> str:
        return _validate_regex(value)


class ExpectedCausalEdgeLabel(BaseModel):
    id: str = Field(min_length=1)
    source_pattern: str = Field(min_length=1)
    target_pattern: str = Field(min_length=1)
    description: str | None = None

    @field_validator("source_pattern", "target_pattern")
    @classmethod
    def validate_edge_pattern(cls, value: str) -> str:
        return _validate_regex(value)


class ExpectedRootCauseLabel(BaseModel):
    top_k: int = Field(default=3, ge=1)
    candidate_patterns: list[str] = Field(min_length=1)

    @field_validator("candidate_patterns")
    @classmethod
    def validate_candidate_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            _validate_regex(pattern)
        return value


class SummaryRubricExpectation(BaseModel):
    key: str = Field(min_length=1)
    description: str
    required_terms: list[str] = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)


class BenchmarkLabels(BaseModel):
    expected_offending_template_patterns: list[str] = Field(min_length=1)
    expected_templates: list[ExpectedTemplateLabel] = Field(min_length=1)
    golden_signal: list[GoldenSignal] = Field(default_factory=list)
    fault_categories: list[str] = Field(default_factory=list)
    key_entities: dict[str, list[str]] = Field(default_factory=dict)
    expected_root_cause: ExpectedRootCauseLabel
    expected_useful_causal_edges: list[ExpectedCausalEdgeLabel] = Field(min_length=1)
    summary_rubric: list[SummaryRubricExpectation] = Field(min_length=1)
    thresholds: dict[str, float] = Field(default_factory=dict)

    @field_validator("expected_offending_template_patterns")
    @classmethod
    def validate_offending_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            _validate_regex(pattern)
        return value

    @model_validator(mode="after")
    def validate_expected_offending_patterns_are_labeled(self) -> "BenchmarkLabels":
        labeled = {item.template_pattern for item in self.expected_templates if item.offending}
        missing = [
            pattern
            for pattern in self.expected_offending_template_patterns
            if pattern not in labeled
        ]
        if missing:
            raise ValueError(
                "expected_offending_template_patterns must also appear as "
                "offending expected_templates"
            )
        return self


class BenchmarkManifest(BaseModel):
    benchmark_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    case_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
    input_paths: list[str] = Field(min_length=1)
    labels_path: str = "labels.json"
    case_context: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class LoadedBenchmark(BaseModel):
    benchmark_dir: Path
    manifest: BenchmarkManifest
    labels: BenchmarkLabels
    input_paths: list[Path]


class MetricScore(BaseModel):
    value: float
    threshold: float | None = None
    passed: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TemplatePatternEvaluation(BaseModel):
    label_id: str
    expected_pattern: str
    matched: bool
    template_id: str | None = None
    expected_golden_signal: str
    actual_golden_signal: str | None = None
    missing_fault_categories: list[str] = Field(default_factory=list)
    extra_fault_categories: list[str] = Field(default_factory=list)


class EdgePatternEvaluation(BaseModel):
    label_id: str
    source_pattern: str
    target_pattern: str
    matched: bool
    edge_id: str | None = None
    confidence: float | None = None
    method: str | None = None


class RootCauseCandidateEvaluation(BaseModel):
    rank: int
    template_id: str
    matched_expected_patterns: list[str] = Field(default_factory=list)


class RootCauseEvaluation(BaseModel):
    top_k: int
    hit: bool
    hit_rank: int | None = None
    accepted_patterns: list[str]
    candidates: list[RootCauseCandidateEvaluation]


class SummaryRubricEvaluation(BaseModel):
    key: str
    score: float
    weight: float
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)


class PipelineCountSummary(BaseModel):
    raw_entries: int
    normalized_logs: int
    templates: int
    samples: int
    annotations: int
    causal_nodes: int
    causal_edges: int


class ReportSafetySummary(BaseModel):
    checked: bool = True
    unsafe_term_count: int = 0


class BenchmarkEvaluationReport(BaseModel):
    benchmark_id: str
    benchmark_name: str
    case_id: str
    analysis_run_id: str
    status: str
    metrics: dict[str, MetricScore]
    pipeline_counts: PipelineCountSummary
    template_patterns: list[TemplatePatternEvaluation]
    useful_causal_edges: list[EdgePatternEvaluation]
    root_cause: RootCauseEvaluation
    summary_rubric: list[SummaryRubricEvaluation]
    safety: ReportSafetySummary = Field(default_factory=ReportSafetySummary)
