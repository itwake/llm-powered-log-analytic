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
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is inactive")
    return user


def require_admin(user: UserRecord) -> UserRecord:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return user


def require_case_permission(
    *,
    store: MetadataStore,
    user: UserRecord,
    case_id: str,
    permission: str,
    hide_forbidden: bool,
):
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    if not store.user_can_access_case(user.id, case_id, permission):
        if hide_forbidden:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="case permission denied")
    return case
