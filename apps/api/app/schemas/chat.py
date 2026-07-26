from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    case_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
