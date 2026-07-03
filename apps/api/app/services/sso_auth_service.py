from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.store import MetadataStore, UserRecord


@dataclass(frozen=True)
class SsoUserProfile:
    username: str
    email: str
    full_name: str | None
    external_id: str | None = None


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _decode_unverified_jwt_payload(token: str) -> dict[str, object]:
    segments = token.split(".")
    if len(segments) < 2:
        raise ValueError("JWT payload is missing")
    payload = json.loads(_base64url_decode(segments[1]).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JWT payload was not a JSON object")
    return payload


def _claim_text(payload: dict[str, object], *names: str) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _display_name_from_email(email: str) -> str | None:
    local_part = email.split("@", 1)[0].strip()
    if not local_part:
        return None
    parts = [part for part in local_part.replace("_", ".").replace("-", ".").split(".") if part]
    if not parts:
        return None
    rendered_parts = []
    for index, part in enumerate(parts):
        normalized = part.lower()
        if 0 < index < len(parts) - 1:
            rendered_parts.append(normalized)
        else:
            rendered_parts.append(normalized[:1].upper() + normalized[1:])
    return " ".join(rendered_parts)


class SsoAuthService:
    def __init__(
        self,
        *,
        app_settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = app_settings
        self.http_client = http_client

    def ensure_enabled(self) -> None:
        if not self.settings.sso_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SSO login is not enabled",
            )

    def build_authorize_url(self, *, redirect_uri: str, state: str) -> str:
        self.ensure_enabled()
        params = {
            'response_type': 'code',
            'client_id': self.settings.sso_client_id,
            'scope': self.settings.sso_authorize_scope,
            'redirect_uri': redirect_uri,
            'state': state,
        }
        return f"{self.settings.sso_authorize_url}?{urlencode(params)}"

    async def exchange_code(self, *, redirect_uri: str, code: str) -> SsoUserProfile:
        self.ensure_enabled()
        authorization_code = code.strip()
        if not authorization_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="missing authorization code",
            )

        client = self.http_client
        close_client = False
        if client is None:
            client = httpx.AsyncClient(**self.settings.sso_httpx_client_kwargs())
            close_client = True

        try:
            response = await client.post(
                self.settings.sso_token_url,
                data={
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "client_id": self.settings.sso_client_id,
                    "scope": self.settings.sso_token_scope,
                    "code": authorization_code,
                },
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="SSO token response was not valid JSON",
                ) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"SSO token exchange failed with HTTP {exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="SSO token exchange failed",
            ) from exc
        finally:
            if close_client:
                await client.aclose()

        access_token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(access_token, str) or not access_token.strip():
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="SSO token response did not include an access token",
            )

        try:
            claims = _decode_unverified_jwt_payload(access_token)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="SSO access token payload was invalid",
            ) from exc
        return self._profile_from_claims(claims)

    def provision_user(self, store: MetadataStore, profile: SsoUserProfile) -> UserRecord:
        self.ensure_enabled()
        external_match = (
            store.get_user_by_external_id(profile.external_id) if profile.external_id else None
        )
        email_match = store.get_user_by_email(profile.email)
        username_match = store.get_user_by_username(profile.username)

        matched_users = {
            user.id: user
            for user in (external_match, email_match, username_match)
            if user is not None
        }
        if len(matched_users) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="SSO account matches multiple local users",
            )

        user = next(iter(matched_users.values()), None)
        if (
            user is not None
            and external_match is None
            and email_match is None
            and username_match is not None
            and username_match.email != profile.email
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="SSO username is already linked to a different local email",
            )

        if user is None:
            try:
                return store.register_user(
                    email=profile.email,
                    username=profile.username,
                    full_name=profile.full_name,
                    password=secrets.token_urlsafe(32),
                    external_id=profile.external_id,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from exc

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="user is inactive",
            )

        updates: dict[str, str] = {}
        if profile.external_id and not user.external_id:
            updates["external_id"] = profile.external_id
        if profile.full_name and not user.full_name:
            updates["full_name"] = profile.full_name
        if updates:
            user = store.update_user_profile(user_id=user.id, **updates)
        return user

    def _profile_from_claims(self, claims: dict[str, object]) -> SsoUserProfile:
        username = _claim_text(claims, "preferred_username")
        email = _claim_text(claims, "email")
        if not username:
            username = email or _claim_text(claims, "upn", "sub")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="SSO access token did not include a usable username",
            )
        if not email:
            if "@" in username:
                email = username
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="SSO access token did not include an email",
                )

        full_name = _claim_text(claims, "name", "display_name")
        if not full_name:
            given_name = _claim_text(claims, "given_name")
            family_name = _claim_text(claims, "family_name")
            composed_name = " ".join(
                part for part in (given_name, family_name) if isinstance(part, str) and part
            ).strip()
            full_name = composed_name or _display_name_from_email(email)

        return SsoUserProfile(
            username=username,
            email=email,
            full_name=full_name,
            external_id=_claim_text(claims, "sub", "oid", "user_id"),
        )

