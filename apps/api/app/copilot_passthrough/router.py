from __future__ import annotations

import json
from collections.abc import Awaitable
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.copilot_passthrough.service import (
    FORWARDED_RESPONSE_HEADERS,
    MAX_REQUEST_BODY_BYTES,
    CopilotPassThrough,
)
from app.dependencies import get_store
from app.services.model_gateway import ModelTransportError
from app.store import sanitize_error_message

router = APIRouter(prefix="/api/copilot", tags=["copilot-passthrough"])

_RELAYED_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "The upstream reply, relayed with its own status code and body."},
    401: {"description": "No bearer token was sent to LogAn."},
    502: {"description": "GitHub or the Copilot API could not be reached from the API host."},
    503: {"description": "The pass-through is disabled on this deployment."},
}
_JSON_OBJECT_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "A Copilot Responses API request, forwarded unchanged.",
                }
            }
        },
    }
}


def get_passthrough(request: Request) -> CopilotPassThrough:
    service = getattr(request.app.state, "copilot_passthrough", None)
    if not isinstance(service, CopilotPassThrough):
        service = CopilotPassThrough(app_settings=get_store(request).settings)
        request.app.state.copilot_passthrough = service
    if not service.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GitHub Copilot pass-through is disabled; set "
                "LOGAN_COPILOT_PASSTHROUGH_ENABLED=true on the API host"
            ),
        )
    return service


@router.post("/token", response_class=Response, responses=_RELAYED_RESPONSES)
async def exchange_copilot_token(
    request: Request,
    service: CopilotPassThrough = Depends(get_passthrough),
) -> Response:
    """Relay GitHub's Copilot token exchange for the caller's own GitHub OAuth token.

    Send the GitHub token as ``Authorization: Bearer``. GitHub's answer (``token``,
    ``expires_at``, ``endpoints``, ...) or its rejection comes back with its status code and body.
    LogAn keeps neither token.
    """
    github_token = _bearer_token(request, expected="a GitHub access token")
    upstream = await _relayed(service.exchange_token(github_token))
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_forwarded_headers(upstream),
    )


@router.post(
    "/responses",
    response_class=Response,
    responses=_RELAYED_RESPONSES,
    openapi_extra=_JSON_OBJECT_BODY,
)
async def relay_copilot_responses(
    request: Request,
    service: CopilotPassThrough = Depends(get_passthrough),
) -> Response:
    """Relay a Copilot Responses API request with the caller's Copilot session token.

    Send the session token from the token exchange as ``Authorization: Bearer`` and the request
    body exactly as the Copilot ``/responses`` endpoint expects it, up to 2 MiB. The body is
    forwarded unchanged with the editor headers the endpoint requires, and the reply streams back
    with its status code and content type, so ``stream: true`` yields server-sent events.
    """
    session_token = _bearer_token(request, expected="a Copilot session token")
    body = await _json_object_body(request)
    upstream = await _relayed(
        service.relay_responses(
            session_token=session_token,
            body=body,
            caller_headers=request.headers,
        )
    )
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers=_forwarded_headers(upstream),
        background=BackgroundTask(upstream.aclose),
    )


def _bearer_token(request: Request, *, expected: str) -> str:
    scheme, _, value = request.headers.get("authorization", "").strip().partition(" ")
    token = value.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"send {expected} as a bearer token in the Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


async def _json_object_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "").strip()
    if declared.isdigit() and int(declared) > MAX_REQUEST_BODY_BYTES:
        raise _too_large()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BODY_BYTES:
            raise _too_large()
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise _not_an_object() from exc
    if not isinstance(payload, dict):
        raise _not_an_object()
    return body


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"request body must be at most {MAX_REQUEST_BODY_BYTES} bytes",
    )


def _not_an_object() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="request body must be a JSON object",
    )


async def _relayed(call: Awaitable[httpx.Response]) -> httpx.Response:
    try:
        return await call
    except ModelTransportError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=sanitize_error_message(exc, max_length=600),
        ) from exc


def _forwarded_headers(upstream: httpx.Response) -> dict[str, str]:
    return {
        name: upstream.headers[name]
        for name in FORWARDED_RESPONSE_HEADERS
        if name in upstream.headers
    }
