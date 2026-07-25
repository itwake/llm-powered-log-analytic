from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_store
from app.store import MetadataStore

router = APIRouter(prefix="/api", tags=["capabilities"])


@router.get("/capabilities")
def capabilities(store: MetadataStore = Depends(get_store)) -> dict[str, object]:
    provider = store.settings.normalized_llm_provider
    llm_enabled = provider == "ai_platform"
    return {
        "models": {
            "enabled": llm_enabled,
            "provider": provider,
            "default_model": store.settings.ai_platform_model if llm_enabled else None,
            "supported_models": [store.settings.ai_platform_model] if llm_enabled else [],
        },
        "views": ["data_summary", "temporal", "tabular", "causal_graph", "causal_summary"],
        "upload": {
            "max_file_size_bytes": 10737418240,
            "supported_extensions": [
                ".log",
                ".txt",
                ".json",
                ".jsonl",
                ".zip",
                ".gz",
                ".tar",
                ".tgz",
            ],
        },
    }
