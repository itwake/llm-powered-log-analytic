from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


GoldenSignal = Literal[
    "error", "availability", "latency", "saturation", "traffic", "information", "unknown"
]

OFFENDING_SIGNALS: set[str] = {"error", "availability", "latency", "saturation", "traffic"}


class EvidenceRef(BaseModel):
    case_id: str
    analysis_run_id: str
    template_id: str | None = None
    log_id: str
    file_path: str
    line_number: int
    timestamp: datetime | None = None


class RawPhysicalLine(BaseModel):
    raw_line_id: str
    file_id: str
    file_path: str
    line_number: int
    raw_text: str
    sha256: str
    ingestion_order: int


class IngestedFile(BaseModel):
    file_id: str
    original_filename: str
    object_uri: str
    size_bytes: int
    sha256: str
    detected_format: str
    lines: list[RawPhysicalLine] = Field(default_factory=list)


class LogEntry(BaseModel):
    log_id: str
    file_id: str
    file_path: str
    line_number: int
    line_numbers: list[int]
    raw_message: str
    raw_line_ids: list[str]
    sha256: str
    ingestion_order: int


class NormalizedLogLine(BaseModel):
    log_id: str
    raw_log_id: str
    case_id: str
    analysis_run_id: str
    file_id: str
    file_path: str
    line_number: int
    line_numbers: list[int]
    timestamp: datetime | None = None
    timestamp_quality: str = "missing"
    level: str | None = None
    service: str | None = None
    message: str
    normalized_message: str
    redacted_message: str
    parsed_fields: dict[str, Any] = Field(default_factory=dict)
    parser_name: str = "logan_regex_v1"
    parser_confidence: float = 0.0
    ingestion_order: int = 0
    template_id: str | None = None
    template_text: str | None = None
    golden_signal: str = "unknown"
    fault_categories: list[str] = Field(default_factory=list)
    entities: dict[str, list[str]] = Field(default_factory=dict)
    severity_score: float = 0.0
    confidence: float = 0.0

    def evidence_ref(self) -> EvidenceRef:
        return EvidenceRef(
            case_id=self.case_id,
            analysis_run_id=self.analysis_run_id,
            template_id=self.template_id,
            log_id=self.log_id,
            file_path=self.file_path,
            line_number=self.line_number,
            timestamp=self.timestamp,
        )


class LogTemplate(BaseModel):
    template_id: str
    template_key: str
    template_text: str
    normalized_template_text: str
    representative_log_id: str | None = None
    occurrence_count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    services: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    sample_values: dict[str, Any] = Field(default_factory=dict)
    drain_cluster_id: str | None = None


class RepresentativeSample(BaseModel):
    sample_id: str
    template_id: str
    log_id: str
    sample_reason: str
    sample_rank: int = 0
    timestamp: datetime | None = None
    level: str | None = None
    service: str | None = None
    message: str
    evidence_ref: EvidenceRef


class TemplateAnnotationResult(BaseModel):
    golden_signal: GoldenSignal
    fault_categories: list[str] = Field(default_factory=list)
    entities: dict[str, list[str]] = Field(default_factory=dict)
    severity_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=1000)


class TemplateAnnotation(TemplateAnnotationResult):
    annotation_id: str
    template_id: str
    analysis_run_id: str
    model_provider: str = "ai_platform"
    model_name: str = "gpt-5.4"
    prompt_version: str = "annotation_v1"
    raw_model_response: dict[str, Any] = Field(default_factory=dict)


class WindowAggregate(BaseModel):
    window_start: datetime
    window_end: datetime
    window_size_seconds: int
    template_id: str | None = None
    service: str | None = None
    golden_signal: str
    fault_category: str | None = None
    count: int


class CausalNode(BaseModel):
    id: str
    label: str
    template_id: str
    golden_signal: str
    fault_categories: list[str] = Field(default_factory=list)
    occurrence_count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    rank_score: float = 0.0
    pagerank_score: float = 0.0
    confidence: float = 0.0
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class CausalEdge(BaseModel):
    id: str
    source: str
    target: str
    source_template_id: str
    target_template_id: str
    edge_type: str = "candidate_cause"
    method: str
    lag_seconds: int | None = None
    support_windows: int = 0
    confidence: float = 0.0
    p_value_adj: float | None = None
    lift: float | None = None
    temporal_precedence_score: float | None = None
    correlation_score: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    needs_validation: bool = True


class RootCauseCandidate(BaseModel):
    template_id: str
    rank: int
    score: float
    reason: str


class CausalGraph(BaseModel):
    nodes: list[CausalNode]
    edges: list[CausalEdge]
    root_cause_candidates: list[RootCauseCandidate]


class CausalSummary(BaseModel):
    summary_markdown: str
    customer_update_markdown: str
    next_actions: list[dict[str, Any]]
    evidence_refs: list[EvidenceRef]
    evidence_claims: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    confidence: float
    edited: bool = False


class ExportArtifact(BaseModel):
    export_id: str
    export_type: Literal["markdown", "html", "json"]
    content: str
    object_uri: str


class AnalysisResult(BaseModel):
    case_id: str
    analysis_run_id: str
    files: list[IngestedFile]
    raw_entries: list[LogEntry]
    normalized_logs: list[NormalizedLogLine]
    templates: list[LogTemplate]
    samples: list[RepresentativeSample]
    annotations: list[TemplateAnnotation]
    temporal: list[WindowAggregate]
    causal_graph: CausalGraph
    causal_summary: CausalSummary
    exports: dict[str, ExportArtifact]
    model_inputs: list[dict[str, Any]] = Field(default_factory=list)
    progress: dict[str, Any] = Field(default_factory=dict)
