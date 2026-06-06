from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.store import MetadataStore, UserRecord


def get_store(request: Request) -> MetadataStore:
    return request.app.state.store


def current_user(request: Request) -> UserRecord:
    store = get_store(request)
    user = store.get_user_by_session(request.cookies.get("logan_session"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user
