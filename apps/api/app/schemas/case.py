from __future__ import annotations

from datetime import datetime
from typing import Any

from logan_analysis.activities.ingestion import MAX_INPUT_BYTES
from pydantic import BaseModel, Field


class CaseCreateRequest(BaseModel):
    title: str = Field(min_length=1)
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
    title: str
    issue_description: str | None = None
    status: str
    product: str | None = None
    service: str | None = None
    environment: str | None = None
    incident_start: datetime | None = None
    incident_end: datetime | None = None
    timezone: str = "UTC"


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str | None = None
    size_bytes: int = Field(gt=0, le=MAX_INPUT_BYTES)


class UploadStartResponse(BaseModel):
    file_id: str
    upload_url: str


class UploadContentResponse(BaseModel):
    file_id: str
    status: str
    sha256: str
    size_bytes: int


class AnalysisRunRequest(BaseModel):
    input_file_ids: list[str] = Field(min_length=1)


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
