from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.model_gateway_factory import ModelGatewayRegistry
from app.store import Store, UserRecord


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_gateway_registry(request: Request) -> ModelGatewayRegistry:
    return request.app.state.gateway_registry


def current_user(request: Request) -> UserRecord:
    store = get_store(request)
    user = store.get_user_by_session(request.cookies.get("logan_session"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


def require_case_owner(
    *,
    store: Store,
    user: UserRecord,
    case_id: str,
):
    case = store.get_case(case_id)
    if not case or case.created_by != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return case
