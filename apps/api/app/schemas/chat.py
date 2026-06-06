from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    case_id: str | None = None
    analysis_run_id: str | None = None
    attachments: list[dict] = Field(default_factory=list)


class TaskExecuteRequest(BaseModel):
    task_name: str
    arguments: dict = Field(default_factory=dict)
