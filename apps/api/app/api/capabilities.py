from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/api", tags=["capabilities"])


@router.get("/capabilities")
def capabilities() -> dict[str, object]:
    return {
        "models": {
            "provider": "github_copilot",
            "default_model": "gpt-5.4",
            "supported_models": [
                "gpt-5.4",
                "gpt-5.4-mini",
                "gpt-5.5",
                "gpt-5.3-codex",
                "gpt-5-mini",
                "gemini-2.5-pro",
                "gemini-3.5-flash",
            ],
        },
        "views": ["data_summary", "temporal", "tabular", "causal_graph", "causal_summary"],
        "upload": {
            "max_file_size_bytes": 10737418240,
            "supported_extensions": [".log", ".txt", ".json", ".jsonl", ".zip", ".gz", ".tar", ".tgz"],
        },
    }
