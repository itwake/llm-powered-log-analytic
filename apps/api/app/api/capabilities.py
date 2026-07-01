from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_store
from app.store import MetadataStore

router = APIRouter(prefix="/api", tags=["capabilities"])


@router.get("/capabilities")
def capabilities(store: MetadataStore = Depends(get_store)) -> dict[str, object]:
    return {
        "models": {
            "provider": store.settings.llm_provider,
            "default_model": store.settings.ai_platform_model,
            "supported_models": [store.settings.ai_platform_model],
        },
        "views": ["data_summary", "temporal", "tabular", "causal_graph", "causal_summary"],
        "upload": {
            "max_file_size_bytes": 10737418240,
            "supported_extensions": [".log", ".txt", ".json", ".jsonl", ".zip", ".gz", ".tar", ".tgz"],
        },
    }
