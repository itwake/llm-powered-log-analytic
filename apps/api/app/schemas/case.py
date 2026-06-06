from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CaseCreateRequest(BaseModel):
    title: str
    issue_description: str | None = None
    product: str | None = None
    service: str | None = None
    environment: str | None = None
    incident_start: datetime | None = None
    incident_end: datetime | None = None
    timezone: str = "UTC"


class CaseResponse(BaseModel):
    case_id: str
    case_key: str
    title: str | None = None
    status: str
    product: str | None = None
    service: str | None = None
    environment: str | None = None
    incident_start: datetime | None = None
    incident_end: datetime | None = None
    timezone: str = "UTC"


class UploadRequest(BaseModel):
    filename: str
    content_type: str | None = None
    size_bytes: int = Field(ge=0)


class UploadCompleteRequest(BaseModel):
    sha256: str


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


class ExportRequest(BaseModel):
    export_type: str
    include_sections: list[str] = Field(default_factory=list)
    redaction_mode: str = "customer_safe"


class FeedbackRequest(BaseModel):
    analysis_run_id: str | None = None
    target_type: str
    target_id: str | None = None
    feedback_type: str
    rating: int | None = None
    comment: str | None = None
    corrected_value: dict[str, Any] | None = None
