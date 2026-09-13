from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    case_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
    provider_id: str | None = Field(
        default=None,
        description="AI provider to answer with; defaults to the run's provider or the "
        "user's default provider.",
    )
    model: str | None = Field(default=None, description="Model enabled on the provider.")
    reasoning_effort: str | None = Field(
        default=None,
        description="Thinking level: low, medium, high, xhigh, or max.",
    )
