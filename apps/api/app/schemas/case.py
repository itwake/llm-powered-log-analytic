from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CaseCreateRequest(BaseModel):
    title: str
    issue_description: str | None = None
    product: str | None = None
    service: str | None = None
    environment: str | None = None
    incident_start: datetime | None = None
    incident_end: datetime | None = None
    timezone: str = "UTC"


class CaseUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    issue_description: str | None = None
    product: str | None = None
    service: str | None = None
    environment: str | None = None
    incident_start: datetime | None = None
    incident_end: datetime | None = None
    timezone: str | None = None


class CaseResponse(BaseModel):
    case_id: str
    case_key: str
    title: str | None = None
    issue_description: str | None = None
    status: str
    product: str | None = None
    service: str | None = None
    environment: str | None = None
    incident_start: datetime | None = None
    incident_end: datetime | None = None
    timezone: str = "UTC"


class CaseCollaboratorRequest(BaseModel):
    user_id: str
    role: str


class CaseCollaboratorResponse(BaseModel):
    id: str
    case_id: str
    user_id: str
    role: str
    added_by: str | None = None
    email: str | None = None
    username: str | None = None
    full_name: str | None = None
    created_at: datetime
    updated_at: datetime


class CaseCollaboratorListResponse(BaseModel):
    items: list[CaseCollaboratorResponse]
    total: int


class UploadRequest(BaseModel):
    filename: str
    content_type: str | None = None
    size_bytes: int = Field(ge=0)
    multipart: bool | None = None
    part_size_bytes: int | None = Field(default=None, gt=0)


class UploadCompletePart(BaseModel):
    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1)


class UploadCompleteRequest(BaseModel):
    sha256: str
    multipart_upload_id: str | None = None
    parts: list[UploadCompletePart] | None = None


class AnalysisRunRequest(BaseModel):
    input_file_ids: list[str] = Field(default_factory=list)
    input_paths: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class AnalysisRunResponse(BaseModel):
    analysis_run_id: str
    run_number: int
    status: str
    current_step: str
    progress: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    model_provider: str
    model_name: str


class AnalysisRunListResponse(BaseModel):
    items: list[AnalysisRunResponse]
    total: int


class JobEventResponse(BaseModel):
    id: str
    case_id: str
    analysis_run_id: str
    step_name: str
    event_type: str
    status: str
    attempt: int
    idempotency_key: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime


class JobEventListResponse(BaseModel):
    items: list[JobEventResponse]
    total: int


class AnalysisStepArtifactResponse(BaseModel):
    id: str
    case_id: str
    analysis_run_id: str
    step_name: str
    artifact_type: str
    object_uri: str
    sha256: str
    size_bytes: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AnalysisStepArtifactListResponse(BaseModel):
    items: list[AnalysisStepArtifactResponse]
    total: int


class ExportRequest(BaseModel):
    export_type: str
    include_sections: list[str] = Field(default_factory=list)
    redaction_mode: str = "customer_safe"


class CausalSummaryUpdateRequest(BaseModel):
    summary_markdown: str = Field(min_length=1, max_length=12000)
    customer_update_markdown: str | None = Field(default=None, max_length=12000)

    @field_validator("summary_markdown")
    @classmethod
    def summary_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary_markdown must not be blank")
        return value


class FeedbackRequest(BaseModel):
    analysis_run_id: str | None = None
    target_type: str
    target_id: str | None = None
    feedback_type: str
    rating: int | None = None
    comment: str | None = None
    corrected_value: dict[str, Any] | None = None
