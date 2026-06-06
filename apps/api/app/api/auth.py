from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import settings
from app.dependencies import current_user, get_store
from app.schemas.auth import AuthUserResponse, LoginRequest, RegisterRequest, UserOut
from app.store import InMemoryStore, UserRecord


router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_user_out(store: InMemoryStore, user: UserRecord) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        has_copilot_credential=store.has_credential(user.id),
    )


@router.post("/register", response_model=AuthUserResponse)
def register(payload: RegisterRequest, store: InMemoryStore = Depends(get_store)) -> AuthUserResponse:
    try:
        user = store.register_user(
            email=str(payload.email),
            username=payload.username,
            full_name=payload.full_name,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AuthUserResponse(user=to_user_out(store, user))


@router.post("/login", response_model=AuthUserResponse)
def login(
    payload: LoginRequest, response: Response, store: InMemoryStore = Depends(get_store)
) -> AuthUserResponse:
    user = store.authenticate(payload.email_or_username, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    token, session = store.create_session(user.id)
    response.set_cookie(
        "logan_session",
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=int((session.expires_at - session.created_at).total_seconds())
        if hasattr(session, "created_at")
        else 31536000,
    )
    return AuthUserResponse(user=to_user_out(store, user))


@router.post("/logout")
def logout(request: Request, response: Response, store: InMemoryStore = Depends(get_store)) -> dict[str, str]:
    store.revoke_session(request.cookies.get("logan_session"))
    response.delete_cookie("logan_session")
    return {"status": "ok"}


@router.get("/me", response_model=AuthUserResponse)
def me(
    user: UserRecord = Depends(current_user), store: InMemoryStore = Depends(get_store)
) -> AuthUserResponse:
    return AuthUserResponse(user=to_user_out(store, user))
