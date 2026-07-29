from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.dependencies import current_user, get_store
from app.schemas.auth import AuthUserResponse, UserOut
from app.services.sso_auth_service import SsoAuthService
from app.store import Store, UserRecord

router = APIRouter(prefix="/api/auth", tags=["auth"])
SSO_STATE_COOKIE_NAME = "logan_sso_state"
SSO_STATE_SALT = "logan-sso-state"
DEFAULT_USER_EMAIL = "local@logan.invalid"
DEFAULT_USER_EXTERNAL_ID = "logan-local-user"
DEFAULT_USER_FULL_NAME = "Local User"
DEFAULT_USER_USERNAME = "local"


def _safe_next_path(value: str | None, fallback: str = "/cases") -> str:
    next_path = (value or "").strip()
    if not next_path.startswith("/") or next_path.startswith("//"):
        return fallback
    if next_path == "/login" or next_path.startswith("/login?"):
        return fallback
    return next_path


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + ("=" * (-len(value) % 4))).encode("utf-8"))


def _sign_state(next_path: str, nonce: str, secret_key: str) -> str:
    payload = _base64url_encode(
        json.dumps({"next": next_path, "nonce": nonce}, separators=(",", ":")).encode()
    )
    signature = hmac.new(
        f"{SSO_STATE_SALT}:{secret_key}".encode(),
        payload.encode(),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{_base64url_encode(signature)}"


def _read_state(token: str, secret_key: str) -> dict[str, str]:
    payload_token, separator, signature_token = token.partition(".")
    if not separator:
        raise HTTPException(status_code=400, detail="invalid SSO state")
    expected = _base64url_encode(
        hmac.new(
            f"{SSO_STATE_SALT}:{secret_key}".encode(),
            payload_token.encode(),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(signature_token, expected):
        raise HTTPException(status_code=400, detail="invalid SSO state")
    try:
        payload = json.loads(_base64url_decode(payload_token))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid SSO state") from exc
    nonce = payload.get("nonce") if isinstance(payload, dict) else None
    if not isinstance(nonce, str) or not nonce:
        raise HTTPException(status_code=400, detail="invalid SSO state")
    next_path = payload.get("next") if isinstance(payload.get("next"), str) else None
    return {"nonce": nonce, "next": _safe_next_path(next_path)}


def _sso_service(request: Request, store: Store) -> SsoAuthService:
    service = getattr(request.app.state, "sso_auth_service", None)
    return service if isinstance(service, SsoAuthService) else SsoAuthService(
        app_settings=store.settings
    )


def _default_user(store: Store) -> UserRecord:
    user = store.get_user_by_external_id(DEFAULT_USER_EXTERNAL_ID)
    if user is not None:
        return user
    try:
        return store.register_user(
            email=DEFAULT_USER_EMAIL,
            username=DEFAULT_USER_USERNAME,
            full_name=DEFAULT_USER_FULL_NAME,
            external_id=DEFAULT_USER_EXTERNAL_ID,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="default user could not be created",
        ) from exc


def _session_redirect(
    *,
    request: Request,
    store: Store,
    user: UserRecord,
    next_path: str,
) -> RedirectResponse:
    token, session = store.create_session(user.id)
    base_url = store.settings.public_web_base_url() or str(request.base_url).rstrip("/")
    response = RedirectResponse(
        f"{base_url}{next_path}",
        status_code=status.HTTP_302_FOUND,
    )
    response.delete_cookie(SSO_STATE_COOKIE_NAME)
    response.set_cookie(
        "logan_session",
        token,
        httponly=True,
        secure=store.settings.secure_cookies,
        samesite="lax",
        max_age=max(int((session.expires_at - session.created_at).total_seconds()), 0),
    )
    return response


@router.get("/login")
def login(
    request: Request,
    store: Store = Depends(get_store),
) -> RedirectResponse:
    next_path = _safe_next_path(request.query_params.get("next"))
    if store.settings.default_user_enabled:
        return _session_redirect(
            request=request,
            store=store,
            user=_default_user(store),
            next_path=next_path,
        )

    service = _sso_service(request, store)
    service.ensure_configured()
    nonce = secrets.token_urlsafe(24)
    state = _sign_state(next_path, nonce, store.settings.secret_key)
    response = RedirectResponse(
        service.build_authorize_url(
            redirect_uri=str(request.url_for("sso_callback")),
            state=state,
        ),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        SSO_STATE_COOKIE_NAME,
        nonce,
        httponly=True,
        secure=store.settings.secure_cookies,
        samesite="lax",
        max_age=300,
    )
    return response


@router.get("/sso/callback")
async def sso_callback(
    request: Request,
    store: Store = Depends(get_store),
) -> RedirectResponse:
    service = _sso_service(request, store)
    service.ensure_configured()
    state = _read_state(
        (request.query_params.get("state") or "").strip(),
        store.settings.secret_key,
    )
    cookie_nonce = (request.cookies.get(SSO_STATE_COOKIE_NAME) or "").strip()
    if not cookie_nonce or not hmac.compare_digest(cookie_nonce, state["nonce"]):
        raise HTTPException(status_code=400, detail="invalid SSO state")
    profile = await service.exchange_code(
        redirect_uri=str(request.url_for("sso_callback")),
        code=request.query_params.get("code") or "",
    )
    user = service.provision_user(store, profile)
    return _session_redirect(
        request=request,
        store=store,
        user=user,
        next_path=state["next"],
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    store: Store = Depends(get_store),
) -> dict[str, str]:
    store.revoke_session(request.cookies.get("logan_session"))
    response.delete_cookie("logan_session")
    return {"status": "ok"}


@router.get("/me", response_model=AuthUserResponse)
def me(user: UserRecord = Depends(current_user)) -> AuthUserResponse:
    return AuthUserResponse(
        user=UserOut(
            id=user.id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
        )
    )
