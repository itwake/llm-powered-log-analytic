from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


UUID_TYPE = String(36).with_variant(PG_UUID(as_uuid=False), "postgresql")
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


def uuid_pk() -> Mapped[str]:
    return mapped_column(UUID_TYPE, primary_key=True)


def jsonb_default() -> Mapped[dict[str, Any]]:
    return mapped_column(JSON_TYPE, nullable=False, default=dict, server_default="{}")


def json_list_default() -> Mapped[list[Any]]:
    return mapped_column(JSON_TYPE, nullable=False, default=list, server_default="[]")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = uuid_pk()
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="engineer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CopilotCredential(Base):
    __tablename__ = "copilot_credentials"

    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    credential_type: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_hint: Mapped[str | None] = mapped_column(Text)
    github_base_url: Mapped[str] = mapped_column(Text, nullable=False, default="https://github.com")
    runtime_type: Mapped[str] = mapped_column(Text, nullable=False, default="github_copilot")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CopilotDeviceAuth(Base):
    __tablename__ = "copilot_device_auth"

    auth_id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    device_code: Mapped[str] = mapped_column(Text, nullable=False)
    user_code: Mapped[str] = mapped_column(Text, nullable=False)
    verification_uri: Mapped[str] = mapped_column(Text, nullable=False)
    verification_uri_complete: Mapped[str] = mapped_column(Text, nullable=False)
    expires_in: Mapped[int] = mapped_column(Integer, nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False)
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    github_base_url: Mapped[str] = mapped_column(Text, nullable=False, default="https://github.com")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = uuid_pk()
    case_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    issue_description: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(Text)
    incident_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(Text, default="UTC")
    status: Mapped[str] = mapped_column(Text, default="created")
    created_by: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (UniqueConstraint("case_id", "run_number"),)

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="queued")
    config_json: Mapped[dict[str, Any]] = jsonb_default()
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_reasoning_effort: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    drain_config_json: Mapped[dict[str, Any]] = jsonb_default()
    causal_config_json: Mapped[dict[str, Any]] = jsonb_default()
    progress_json: Mapped[dict[str, Any]] = jsonb_default()
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "idempotency_key", "event_type"),
    )

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(
        UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict, server_default="{}"
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RawFile(Base):
    __tablename__ = "raw_files"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"))
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(Text)
    upload_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detected_format: Mapped[str | None] = mapped_column(Text)
    file_role: Mapped[str] = mapped_column(Text, default="log")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RawLogLine(Base):
    __tablename__ = "raw_log_lines"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    file_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("raw_files.id"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text_redacted: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NormalizedLogLine(Base):
    __tablename__ = "normalized_log_lines"

    id: Mapped[str] = uuid_pk()
    raw_log_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("raw_log_lines.id"), nullable=False)
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timestamp_quality: Mapped[str] = mapped_column(Text, default="parsed")
    level: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_message: Mapped[str] = mapped_column(Text, nullable=False)
    redacted_message: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_fields: Mapped[dict[str, Any]] = jsonb_default()
    parser_name: Mapped[str | None] = mapped_column(Text)
    parser_confidence: Mapped[float] = mapped_column(Float, default=0)
    template_id: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("log_templates.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LogTemplate(Base):
    __tablename__ = "log_templates"
    __table_args__ = (UniqueConstraint("analysis_run_id", "template_key"),)

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_template_text: Mapped[str] = mapped_column(Text, nullable=False)
    representative_log_id: Mapped[str | None] = mapped_column(UUID_TYPE)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    services: Mapped[list[Any]] = json_list_default()
    files: Mapped[list[Any]] = json_list_default()
    sample_values: Mapped[dict[str, Any]] = jsonb_default()
    drain_cluster_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepresentativeSample(Base):
    __tablename__ = "representative_samples"

    id: Mapped[str] = uuid_pk()
    template_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("log_templates.id"), nullable=False)
    log_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("normalized_log_lines.id"), nullable=False)
    sample_reason: Mapped[str] = mapped_column(Text, nullable=False)
    sample_rank: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateAnnotation(Base):
    __tablename__ = "template_annotations"
    __table_args__ = (UniqueConstraint("template_id", "prompt_version", "model_name"),)

    id: Mapped[str] = uuid_pk()
    template_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("log_templates.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    golden_signal: Mapped[str] = mapped_column(Text, nullable=False)
    fault_categories: Mapped[list[Any]] = json_list_default()
    entities: Mapped[dict[str, Any]] = jsonb_default()
    severity_score: Mapped[float] = mapped_column(Float, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    rationale: Mapped[str | None] = mapped_column(Text)
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    raw_model_response: Mapped[dict[str, Any]] = jsonb_default()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimeWindowSignal(Base):
    __tablename__ = "time_window_signals"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_size_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    template_id: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("log_templates.id"))
    service: Mapped[str | None] = mapped_column(Text)
    golden_signal: Mapped[str] = mapped_column(Text, nullable=False)
    fault_category: Mapped[str | None] = mapped_column(Text)
    count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CausalNode(Base):
    __tablename__ = "causal_nodes"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    template_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("log_templates.id"), nullable=False)
    node_type: Mapped[str] = mapped_column(Text, default="template")
    rank_score: Mapped[float] = mapped_column(Float, default=0)
    pagerank_score: Mapped[float] = mapped_column(Float, default=0)
    golden_signal: Mapped[str | None] = mapped_column(Text)
    fault_categories: Mapped[list[Any]] = json_list_default()
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CausalEdge(Base):
    __tablename__ = "causal_edges"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    source_template_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("log_templates.id"), nullable=False)
    target_template_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("log_templates.id"), nullable=False)
    edge_type: Mapped[str] = mapped_column(Text, default="candidate_cause")
    method: Mapped[str] = mapped_column(Text, nullable=False)
    lag_seconds: Mapped[int | None] = mapped_column(Integer)
    support_windows: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    p_value_adj: Mapped[float | None] = mapped_column(Float)
    lift: Mapped[float | None] = mapped_column(Float)
    temporal_precedence_score: Mapped[float | None] = mapped_column(Float)
    correlation_score: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict[str, Any]] = jsonb_default()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CausalSummary(Base):
    __tablename__ = "causal_summaries"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    summary_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    customer_update_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    next_actions_json: Mapped[list[Any]] = json_list_default()
    evidence_refs_json: Mapped[list[Any]] = json_list_default()
    confidence: Mapped[float] = mapped_column(Float, default=0)
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    raw_model_response: Mapped[dict[str, Any]] = jsonb_default()
    edited_by: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"))
    user_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(Text)
    feedback_type: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    corrected_value: Mapped[dict[str, Any]] = jsonb_default()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("analysis_runs.id"), nullable=False)
    export_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[str | None] = mapped_column(UUID_TYPE, ForeignKey("cases.id"))
    ip_address: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
