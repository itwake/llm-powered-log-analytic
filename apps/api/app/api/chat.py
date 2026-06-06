from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import current_user, get_store
from app.schemas.chat import ChatRequest, TaskExecuteRequest
from app.store import InMemoryStore, UserRecord


router = APIRouter(prefix="/api", tags=["runtime"])


@router.post("/chat")
def chat(
    payload: ChatRequest,
    user: UserRecord = Depends(current_user),
    store: InMemoryStore = Depends(get_store),
) -> dict[str, object]:
    del user
    if payload.analysis_run_id and payload.analysis_run_id in store.runs:
        result = store.runs[payload.analysis_run_id].result
        if result:
            refs = [ref.model_dump(mode="json") for ref in result.causal_summary.evidence_refs[:3]]
            return {
                "message": "The current analysis treats the leading chain as candidate evidence, not a definitive root cause. The ranking is based on temporal precedence, service/entity evidence, lift, and PageRank-style scoring, and it needs validation.",
                "evidence_refs": refs,
            }
    return {
        "message": "No case analysis context was found for this chat request.",
        "evidence_refs": [],
    }


@router.post("/tasks/execute")
def execute_task(
    payload: TaskExecuteRequest,
    user: UserRecord = Depends(current_user),
) -> dict[str, object]:
    return {
        "task_id": f"task-{payload.task_name}",
        "status": "accepted",
        "runtime_type": "github_copilot",
        "created_by": user.id,
        "arguments": payload.arguments,
    }
