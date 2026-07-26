from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    case_id: str | None = None
    analysis_run_id: str | None = None
