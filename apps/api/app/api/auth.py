from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.dependencies import current_user, get_store
from app.schemas.auth import AuthUserResponse, UserOut
from app.store import MetadataStore, UserRecord
from app.services.sso_auth_service import SsoAuthService


router = APIRouter(prefix="/api/auth", tags=["auth"])
SSO_STATE_COOKIE_NAME = "logan_sso_state"
SSO_STATE_SALT = "logan-sso-state"
SSO_MOCK_CODE_SALT = "logan-sso-mock-code"
logger = logging.getLogger(__name__)


def _safe_next_path(value: str | None, fallback: str = "/cases") -> str:
    next_path = (value or "").strip()
    if not next_path.startswith("/") or next_path.startswith("//"):
        return fallback
    if next_path == "/login" or next_path.startswith("/login?"):
        return fallback
    if next_path == "/register" or next_path.startswith("/register?"):
        return fallback
    return next_path


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _state_hint(value: str | None) -> str:
    if not value:
        return "missing"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _unsigned_jwt(payload: dict[str, str]) -> str:
    header = _base64url_encode(
        json.dumps({"alg": "none", "typ": "JWT"}, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    body = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{header}.{body}."


def _sign_sso_state(next_path: str, nonce: str, secret_key: str) -> str:
    payload = _base64url_encode(
        json.dumps({"next": next_path, "nonce": nonce}, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    signature = hmac.new(
        f"{SSO_STATE_SALT}:{secret_key}".encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{_base64url_encode(signature)}"


def _read_sso_state(token: str, secret_key: str) -> dict[str, str]:
    payload_token, separator, signature_token = token.partition(".")
    if not separator or not payload_token or not signature_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid SSO state")

    expected_signature = _base64url_encode(
        hmac.new(
            f"{SSO_STATE_SALT}:{secret_key}".encode("utf-8"),
            payload_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(signature_token, expected_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid SSO state")

    try:
        payload = json.loads(_base64url_decode(payload_token).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid SSO state") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid SSO state")

    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid SSO state")
    next_value = payload.get("next") if isinstance(payload.get("next"), str) else None
    return {"nonce": nonce.strip(), "next": _safe_next_path(next_value)}


def _issue_mock_sso_code(
    *,
    username: str,
    email: str,
    full_name: str | None,
    secret_key: str,
) -> str:
    payload: dict[str, str] = {
        "sub": f"mock-sso:{username}",
        "preferred_username": username,
        "email": email,
    }
    if full_name:
        payload["name"] = full_name
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        f"{SSO_MOCK_CODE_SALT}:{secret_key}".encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def _read_mock_sso_code(code: str, secret_key: str) -> dict[str, str]:
    payload_token, separator, signature_token = code.partition(".")
    if not separator or not payload_token or not signature_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid mock SSO code")
    expected_signature = _base64url_encode(
        hmac.new(
            f"{SSO_MOCK_CODE_SALT}:{secret_key}".encode("utf-8"),
            payload_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(signature_token, expected_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid mock SSO code")
    try:
        payload = json.loads(_base64url_decode(payload_token).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid mock SSO code") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid mock SSO code")

    claims: dict[str, str] = {}
    for key in ("sub", "preferred_username", "email", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            claims[key] = value.strip()
    if "preferred_username" not in claims or "email" not in claims or "sub" not in claims:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid mock SSO code")
    return claims


def _session_max_age(session: object | None) -> int | None:
    if session is None:
        return None
    expires_at = getattr(session, "expires_at", None)
    created_at = getattr(session, "created_at", None)
    if expires_at is None or created_at is None:
        return None
    try:
        return max(int((expires_at - created_at).total_seconds()), 0)
    except Exception:
        return None


def _set_session_cookie(
    response: Response,
    *,
    token: str,
    store: MetadataStore,
    session: object | None = None,
) -> None:
    cookie_kwargs: dict[str, object] = {
        "httponly": True,
        "secure": store.settings.secure_cookies,
        "samesite": "lax",
    }
    max_age = _session_max_age(session)
    if max_age is not None:
        cookie_kwargs["max_age"] = max_age
    response.set_cookie("logan_session", token, **cookie_kwargs)


def _get_sso_auth_service(request: Request, store: MetadataStore) -> SsoAuthService:
    service = getattr(request.app.state, "sso_auth_service", None)
    if isinstance(service, SsoAuthService):
        return service
    return SsoAuthService(app_settings=store.settings)


def _ensure_mock_sso_enabled(store: MetadataStore) -> None:
    if not store.settings.sso_mock_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def _mock_sso_claims(request: Request, store: MetadataStore) -> tuple[str, str, str | None]:
    username = (
        request.query_params.get("mock_username")
        or request.query_params.get("login_hint")
        or store.settings.sso_mock_username
    ).strip()
    email = (request.query_params.get("mock_email") or store.settings.sso_mock_email).strip()
    full_name = (request.query_params.get("mock_full_name") or store.settings.sso_mock_full_name).strip()
    if not username:
        username = email
    if not email:
        email = username if "@" in username else f"{username}@example.com"
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mock SSO username was not configured",
        )
    return username, email, full_name or None


def _web_redirect_base(request: Request, store: MetadataStore) -> str:
    return store.settings.public_web_base_url() or str(request.base_url).rstrip("/")


def to_user_out(store: MetadataStore, user: UserRecord) -> UserOut:
    return UserOut(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )


def _raise_password_auth_removed() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="username/password authentication has been removed; use SSO via /api/auth/sso/login",
    )


@router.post("/register", include_in_schema=False)
def register_removed() -> None:
    _raise_password_auth_removed()


@router.post("/login", include_in_schema=False)
def login_removed() -> None:
    _raise_password_auth_removed()


@router.get("/sso/login")
async def sso_login(
    request: Request,
    store: MetadataStore = Depends(get_store),
) -> RedirectResponse:
    service = _get_sso_auth_service(request, store)
    service.ensure_enabled()
    next_path = _safe_next_path(request.query_params.get("next"))
    nonce = secrets.token_urlsafe(24)
    state = _sign_sso_state(next_path, nonce, store.settings.secret_key)
    redirect_uri = str(request.url_for("sso_callback"))
    logger.info(
        "sso.login state_issued next=%s redirect_uri=%s request_host=%s scheme=%s "
        "secure_cookie=%s state_hint=%s nonce_hint=%s",
        next_path,
        redirect_uri,
        request.headers.get("host"),
        request.url.scheme,
        store.settings.secure_cookies,
        _state_hint(state),
        _state_hint(nonce),
    )
    response = RedirectResponse(
        url=service.build_authorize_url(
            redirect_uri=redirect_uri,
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


@router.get("/sso/mock/authorize", include_in_schema=False)
def sso_mock_authorize(
    request: Request,
    store: MetadataStore = Depends(get_store),
) -> RedirectResponse:
    _ensure_mock_sso_enabled(store)
    redirect_uri = (request.query_params.get("redirect_uri") or "").strip()
    if not redirect_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing redirect_uri")
    username, email, full_name = _mock_sso_claims(request, store)
    code = _issue_mock_sso_code(
        username=username,
        email=email,
        full_name=full_name,
        secret_key=store.settings.secret_key,
    )
    query = {"code": code}
    state = (request.query_params.get("state") or "").strip()
    if state:
        query["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        url=f"{redirect_uri}{separator}{urlencode(query)}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/sso/mock/token", include_in_schema=False)
async def sso_mock_token(
    request: Request,
    store: MetadataStore = Depends(get_store),
) -> dict[str, str]:
    _ensure_mock_sso_enabled(store)
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    grant_type = (form.get("grant_type") or [""])[0].strip()
    if grant_type and grant_type != "authorization_code":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported grant_type")
    client_id = (form.get("client_id") or [""])[0].strip()
    if client_id and client_id != store.settings.sso_client_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid client_id")
    code = (form.get("code") or [""])[0].strip()
    claims = _read_mock_sso_code(code, store.settings.secret_key)
    return {
        "access_token": _unsigned_jwt(claims),
        "token_type": "Bearer",
    }


@router.get("/sso/callback")
async def sso_callback(
    request: Request,
    store: MetadataStore = Depends(get_store),
) -> RedirectResponse:
    service = _get_sso_auth_service(request, store)
    service.ensure_enabled()
    raw_state = (request.query_params.get("state") or "").strip()
    try:
        state = _read_sso_state(raw_state, store.settings.secret_key)
    except HTTPException:
        logger.warning(
            "sso.callback invalid_state_token has_state=%s state_hint=%s request_host=%s scheme=%s",
            bool(raw_state),
            _state_hint(raw_state),
            request.headers.get("host"),
            request.url.scheme,
        )
        raise
    cookie_nonce = (request.cookies.get(SSO_STATE_COOKIE_NAME) or "").strip()
    if not cookie_nonce or cookie_nonce != state["nonce"]:
        logger.warning(
            "sso.callback state_cookie_mismatch has_cookie=%s cookie_nonce_hint=%s "
            "state_nonce_hint=%s state_hint=%s request_host=%s scheme=%s secure_cookie=%s",
            bool(cookie_nonce),
            _state_hint(cookie_nonce),
            _state_hint(state["nonce"]),
            _state_hint(raw_state),
            request.headers.get("host"),
            request.url.scheme,
            store.settings.secure_cookies,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid SSO state")

    profile = await service.exchange_code(
        redirect_uri=str(request.url_for("sso_callback")),
        code=request.query_params.get("code") or "",
    )
    user = service.provision_user(store, profile)
    token, session = store.create_session(user.id)
    logger.info(
        "sso.callback completed user_id=%s next=%s state_hint=%s",
        user.id,
        state["next"],
        _state_hint(raw_state),
    )

    response = RedirectResponse(
        url=f"{_web_redirect_base(request, store)}{state['next']}",
        status_code=status.HTTP_302_FOUND,
    )
    response.delete_cookie(
        SSO_STATE_COOKIE_NAME,
        secure=store.settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    _set_session_cookie(response, token=token, store=store, session=session)
    return response


@router.post("/logout")
def logout(request: Request, response: Response, store: MetadataStore = Depends(get_store)) -> dict[str, str]:
    store.revoke_session(request.cookies.get("logan_session"))
    response.delete_cookie("logan_session")
    return {"status": "ok"}


@router.get("/me", response_model=AuthUserResponse)
def me(
    user: UserRecord = Depends(current_user), store: MetadataStore = Depends(get_store)
) -> AuthUserResponse:
    return AuthUserResponse(user=to_user_out(store, user))
