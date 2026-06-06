from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.copilot_auth_service import DeviceCodeClient
from app.services.copilot_model_gateway import CopilotModelGateway
from app.store import MetadataStore, UserRecord


def get_store(request: Request) -> MetadataStore:
    return request.app.state.store


def get_copilot_auth_client(request: Request) -> DeviceCodeClient:
    return request.app.state.copilot_auth_client


def get_model_gateway(request: Request) -> CopilotModelGateway:
    return request.app.state.model_gateway


def current_user(request: Request) -> UserRecord:
    store = get_store(request)
    user = store.get_user_by_session(request.cookies.get("logan_session"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user
