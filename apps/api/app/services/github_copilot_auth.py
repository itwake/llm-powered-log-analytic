"""GitHub device authorization for the GitHub Copilot provider.

The flow follows the Copilot editor plugins: request a device code from github.com, let the
user confirm the code in the browser, then poll for the OAuth access token. Pending
authorizations are kept in process memory only, scoped to the signing-in user, and the token
never travels back to the browser; the API stores it encrypted on the provider record.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import Settings, settings
from app.services.github_copilot_model_gateway import GITHUB_API_BASE_URL, copilot_plugin_headers
from app.services.model_gateway import (
    ModelTransportError,
    http_error_message,
    sanitized_response_detail,
    transport_error_message,
)

COPILOT_OAUTH_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_BASE_URL = "https://github.com"
GITHUB_DEVICE_CODE_PATH = "/login/device/code"
GITHUB_ACCESS_TOKEN_PATH = "/login/oauth/access_token"
GITHUB_USER_PATH = "/user"
DEVICE_FLOW_SCOPE = "read:user"
DEFAULT_DEVICE_CODE_TTL_SECONDS = 900
DEFAULT_POLL_INTERVAL_SECONDS = 5
MAX_PENDING_AUTHORIZATIONS_PER_USER = 5


@dataclass
class PendingDeviceAuthorization:
    auth_id: str
    user_id: str
    provider_id: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_at: datetime
    interval: int
    device_code: str = field(repr=False)
    last_polled_at: float | None = None

    @property
    def expires_in(self) -> int:
        return max(0, int((self.expires_at - datetime.now(UTC)).total_seconds()))


@dataclass(frozen=True)
class DeviceAuthorizationResult:
    status: str
    github_login: str | None = None
    message: str | None = None
    interval: int | None = None
    access_token: str | None = field(default=None, repr=False)


class GitHubDeviceFlow:
    _JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
        github_base_url: str = GITHUB_BASE_URL,
        github_api_base_url: str = GITHUB_API_BASE_URL,
    ) -> None:
        self.settings = app_settings
        self.http_client = http_client or httpx.AsyncClient(
            **app_settings.github_copilot_httpx_client_kwargs()
        )
        self.github_base_url = github_base_url.rstrip("/")
        self.github_api_base_url = github_api_base_url.rstrip("/")
        self._pending: dict[str, PendingDeviceAuthorization] = {}

    async def aclose(self) -> None:
        await self.http_client.aclose()

    def pending_for(self, *, user_id: str, auth_id: str) -> PendingDeviceAuthorization | None:
        self._cleanup_expired()
        record = self._pending.get(auth_id)
        if record is None or record.user_id != user_id:
            return None
        return record

    async def start(self, *, user_id: str, provider_id: str) -> PendingDeviceAuthorization:
        self._cleanup_expired()
        owned = [record for record in self._pending.values() if record.user_id == user_id]
        for stale in owned[: max(0, len(owned) - MAX_PENDING_AUTHORIZATIONS_PER_USER + 1)]:
            self._pending.pop(stale.auth_id, None)
        endpoint = f"{self.github_base_url}{GITHUB_DEVICE_CODE_PATH}"
        try:
            response = await self.http_client.post(
                endpoint,
                headers={**self._JSON_HEADERS, **copilot_plugin_headers()},
                json={"client_id": COPILOT_OAUTH_CLIENT_ID, "scope": DEVICE_FLOW_SCOPE},
            )
            response.raise_for_status()
            data = _json_object(response)
        except httpx.HTTPStatusError as exc:
            raise ModelTransportError(
                http_error_message("GitHub device authorization", exc)
            ) from exc
        except ModelTransportError:
            raise
        except Exception as exc:
            raise ModelTransportError(
                transport_error_message("GitHub device authorization", exc)
            ) from exc

        device_code = str(data.get("device_code") or "").strip()
        user_code = str(data.get("user_code") or "").strip()
        verification_uri = str(data.get("verification_uri") or "").strip()
        if not device_code or not user_code or not verification_uri:
            raise ModelTransportError(
                "GitHub device authorization response is missing device_code, user_code, "
                "or verification_uri"
            )
        expires_in = _positive_int(data.get("expires_in"), DEFAULT_DEVICE_CODE_TTL_SECONDS)
        interval = _positive_int(data.get("interval"), DEFAULT_POLL_INTERVAL_SECONDS)
        record = PendingDeviceAuthorization(
            auth_id=str(uuid.uuid4()),
            user_id=user_id,
            provider_id=provider_id,
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=(
                str(data.get("verification_uri_complete") or "").strip() or verification_uri
            ),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            interval=interval,
            device_code=device_code,
        )
        self._pending[record.auth_id] = record
        return record

    async def check(self, *, user_id: str, auth_id: str) -> DeviceAuthorizationResult:
        record = self.pending_for(user_id=user_id, auth_id=auth_id)
        if record is None:
            return DeviceAuthorizationResult(
                status="expired",
                message="The GitHub authorization request expired or was not found; start again.",
            )
        now = time.monotonic()
        if record.last_polled_at is not None and now - record.last_polled_at < record.interval:
            return DeviceAuthorizationResult(status="pending", interval=record.interval)
        record.last_polled_at = now

        endpoint = f"{self.github_base_url}{GITHUB_ACCESS_TOKEN_PATH}"
        try:
            response = await self.http_client.post(
                endpoint,
                headers={**self._JSON_HEADERS, **copilot_plugin_headers()},
                json={
                    "client_id": COPILOT_OAUTH_CLIENT_ID,
                    "device_code": record.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        except Exception as exc:
            return DeviceAuthorizationResult(
                status="failed",
                message=transport_error_message("GitHub device authorization", exc),
            )
        if response.status_code >= 500:
            return DeviceAuthorizationResult(
                status="failed",
                message=(
                    "GitHub device authorization failed with HTTP "
                    f"{response.status_code}: {sanitized_response_detail(response)}"
                ),
            )
        try:
            body: dict[str, Any] = _json_object(response)
        except ModelTransportError as exc:
            return DeviceAuthorizationResult(status="failed", message=str(exc))

        error = str(body.get("error") or "").strip()
        if error == "authorization_pending":
            return DeviceAuthorizationResult(status="pending", interval=record.interval)
        if error == "slow_down":
            record.interval += 5
            return DeviceAuthorizationResult(status="pending", interval=record.interval)
        if error == "expired_token":
            self._pending.pop(auth_id, None)
            return DeviceAuthorizationResult(
                status="expired",
                message="The GitHub device code expired before it was confirmed; start again.",
            )
        if error in {"access_denied", "authorization_declined"}:
            self._pending.pop(auth_id, None)
            return DeviceAuthorizationResult(
                status="declined",
                message="GitHub reported that the authorization was declined.",
            )
        access_token = str(body.get("access_token") or "").strip()
        if access_token:
            self._pending.pop(auth_id, None)
            login = await self._fetch_login(access_token)
            return DeviceAuthorizationResult(
                status="authorized",
                github_login=login,
                access_token=access_token,
            )
        description = str(body.get("error_description") or "").strip()
        message = description or error or f"GitHub returned HTTP {response.status_code}"
        return DeviceAuthorizationResult(
            status="failed",
            message=f"GitHub device authorization failed: {message}"[:500],
        )

    async def _fetch_login(self, access_token: str) -> str | None:
        try:
            response = await self.http_client.get(
                f"{self.github_api_base_url}{GITHUB_USER_PATH}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    **copilot_plugin_headers(),
                },
            )
            response.raise_for_status()
            data = _json_object(response)
        except Exception:
            return None
        login = data.get("login")
        return str(login).strip() if isinstance(login, str) and login.strip() else None

    def _cleanup_expired(self) -> None:
        now = datetime.now(UTC)
        for auth_id in [key for key, item in self._pending.items() if item.expires_at <= now]:
            self._pending.pop(auth_id, None)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise ModelTransportError("GitHub returned a non-JSON response") from exc
    return payload if isinstance(payload, dict) else {}


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return default
        return parsed if parsed > 0 else default
    return default
