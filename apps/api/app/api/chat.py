from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.dependencies import current_user, get_model_gateway, get_store
from app.schemas.chat import ChatRequest, TaskExecuteRequest
from app.services.copilot_model_gateway import CopilotGatewayError
from app.store import MetadataStore, UserRecord, sanitize_error_message


router = APIRouter(prefix="/api", tags=["runtime"])
CHAT_FALLBACK_MESSAGE = "No case analysis context was found for this chat request."
CHAT_INSTRUCTIONS = (
    "You are assisting with an incident analysis workspace. Answer cautiously and stay "
    "evidence-bound. Treat causal chains as candidates that need validation. Use only the "
    "provided redacted analysis context, call out uncertainty, and do not invent log details."
)


@router.post("/chat")
def chat(
    payload: ChatRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
) -> dict[str, object]:
    del user
    if payload.case_id and payload.analysis_run_id:
        result = store.get_analysis_result(payload.case_id, payload.analysis_run_id)
        if result:
            refs = [ref.model_dump(mode="json") for ref in result.causal_summary.evidence_refs[:3]]
            return {
                "message": "The current analysis treats the leading chain as candidate evidence, not a definitive root cause. The ranking is based on temporal precedence, service/entity evidence, lift, and PageRank-style scoring, and it needs validation.",
                "evidence_refs": refs,
            }
    return {
        "message": CHAT_FALLBACK_MESSAGE,
        "evidence_refs": [],
    }


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    user: UserRecord = Depends(current_user),
    store: MetadataStore = Depends(get_store),
    gateway: Any = Depends(get_model_gateway),
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        context = _analysis_chat_context(store, payload)
        if context is None:
            yield _sse_frame("delta", {"delta": CHAT_FALLBACK_MESSAGE})
            yield _sse_frame("evidence", {"evidence_refs": []})
            yield _sse_frame("done", {"message": CHAT_FALLBACK_MESSAGE})
            return

        evidence_refs = context["evidence_refs"]
        message_parts: list[str] = []
        try:
            stream = await gateway.responses(
                user_id=user.id,
                model=store.settings.copilot_model,
                instructions=CHAT_INSTRUCTIONS,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps(context, separators=(",", ":")),
                            }
                        ],
                    }
                ],
                stream=True,
                metadata={
                    "case_id": payload.case_id,
                    "analysis_run_id": payload.analysis_run_id,
                    "purpose": "case_chat",
                },
                reasoning_effort=store.settings.copilot_reasoning_effort,
            )
            yield _sse_frame("evidence", {"evidence_refs": evidence_refs})
            completed_text = ""
            async for event in stream:
                if event.get("type") == "message.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str) and delta:
                        message_parts.append(delta)
                        yield _sse_frame("delta", {"delta": delta})
                elif event.get("type") == "message.completed":
                    output_text = event.get("output_text")
                    if isinstance(output_text, str):
                        completed_text = output_text
            message = "".join(message_parts) or completed_text
            if completed_text and not message_parts:
                message_parts.append(completed_text)
                yield _sse_frame("delta", {"delta": completed_text})
                message = completed_text
            yield _sse_frame("done", {"message": message})
        except CopilotGatewayError as exc:
            yield _sse_frame("error", {"message": sanitize_error_message(exc)})
        except Exception as exc:
            yield _sse_frame("error", {"message": sanitize_error_message(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")


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


def _sse_frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _analysis_chat_context(
    store: MetadataStore,
    payload: ChatRequest,
) -> dict[str, Any] | None:
    if not payload.case_id or not payload.analysis_run_id:
        return None
    result = store.get_analysis_result(payload.case_id, payload.analysis_run_id)
    if result is None:
        return None

    evidence_refs = [
        ref.model_dump(mode="json") for ref in result.causal_summary.evidence_refs[:5]
    ]
    return {
        "user_message": _compact_context_text(payload.message, max_length=1000),
        "case_id": payload.case_id,
        "analysis_run_id": payload.analysis_run_id,
        "causal_summary": _compact_context_text(
            result.causal_summary.summary_markdown,
            max_length=2500,
        ),
        "evidence_refs": evidence_refs,
        "summary_rows": _summary_rows(result),
    }


def _summary_rows(result: Any) -> list[dict[str, Any]]:
    annotations = {annotation.template_id: annotation for annotation in result.annotations}
    rows: list[dict[str, Any]] = []
    for template in result.templates:
        annotation = annotations.get(template.template_id)
        if annotation is None:
            continue
        rows.append(
            {
                "template_id": template.template_id,
                "template_text": _compact_context_text(template.template_text, max_length=500),
                "golden_signal": annotation.golden_signal,
                "fault_categories": annotation.fault_categories,
                "entities": annotation.entities,
                "occurrence_count": template.occurrence_count,
                "first_seen": template.first_seen.isoformat() if template.first_seen else None,
                "last_seen": template.last_seen.isoformat() if template.last_seen else None,
                "services": template.services[:5],
                "severity_score": annotation.severity_score,
                "confidence": annotation.confidence,
                "rationale": _compact_context_text(annotation.rationale, max_length=500),
            }
        )
    rows.sort(key=lambda row: (-float(row["severity_score"]), row["first_seen"] or ""))
    return rows[:5]


def _compact_context_text(value: str, *, max_length: int) -> str:
    sanitized = sanitize_error_message(value, max_length=max_length)
    return " ".join(sanitized.split())
