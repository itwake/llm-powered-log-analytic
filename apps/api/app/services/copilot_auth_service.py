from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol

import httpx

from app.config import Settings, settings
from app.store import CopilotAuthRecord, MetadataStore, UserRecord


GITHUB_COPILOT_USER_AGENT = "GitHubCopilotChat/0.35.0"
GITHUB_COPILOT_OAUTH_BASE_URL = "https://github.com"
DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int = 900
    interval: int = 5


@dataclass(frozen=True)
class DeviceCodePollResult:
    status: str
    message: str
    access_token: str | None = None
    interval_delta_seconds: int = 0


class DeviceCodeClient(Protocol):
    enforce_poll_interval: bool

    def start(self, github_base_url: str) -> DeviceCodeResponse: ...

    def check(self, record: CopilotAuthRecord) -> DeviceCodePollResult: ...


class GitHubDeviceCodeClient:
    enforce_poll_interval = True

    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = app_settings
        self.http_client = http_client or httpx.Client(
            timeout=app_settings.copilot_timeout_seconds,
            verify=app_settings.copilot_httpx_verify(),
        )

    def start(self, github_base_url: str) -> DeviceCodeResponse:
        response = self.http_client.post(
            f"{GITHUB_COPILOT_OAUTH_BASE_URL}/login/device/code",
            json={"client_id": self.settings.copilot_oauth_client_id, "scope": "read:user"},
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        return DeviceCodeResponse(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data["verification_uri"],
            verification_uri_complete=data.get("verification_uri_complete")
            or f"{data['verification_uri']}?user_code={data['user_code']}",
            expires_in=int(data.get("expires_in", 900)),
            interval=int(data.get("interval", 5)),
        )

    def check(self, record: CopilotAuthRecord) -> DeviceCodePollResult:
        response = self.http_client.post(
            f"{GITHUB_COPILOT_OAUTH_BASE_URL}/login/oauth/access_token",
            json={
                "client_id": self.settings.copilot_oauth_client_id,
                "device_code": record.device_code,
                "grant_type": DEVICE_CODE_GRANT_TYPE,
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        access_token = data.get("access_token")
        if access_token:
            return DeviceCodePollResult(
                status="authorized",
                message="authorized",
                access_token=access_token,
            )
        error = str(data.get("error") or "authorization_pending")
        if error == "authorization_pending":
            return DeviceCodePollResult(status="pending", message=error)
        if error == "slow_down":
            return DeviceCodePollResult(status="pending", message=error, interval_delta_seconds=5)
        if error == "expired_token":
            return DeviceCodePollResult(status="expired", message=error)
        if error in {"access_denied", "authorization_declined"}:
            return DeviceCodePollResult(status="declined", message=error)
        return DeviceCodePollResult(status="error", message=error)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": GITHUB_COPILOT_USER_AGENT,
        }


class MockGitHubDeviceClient:
    enforce_poll_interval = False

    def __init__(self, poll_results: list[DeviceCodePollResult] | None = None) -> None:
        self.poll_results = poll_results or [
            DeviceCodePollResult(status="pending", message="authorization_pending"),
            DeviceCodePollResult(
                status="authorized",
                message="authorized",
                access_token="gho_mock_source_token",
            ),
        ]

    def start(self, github_base_url: str) -> DeviceCodeResponse:
        user_code = "LOGAN-TEST"
        return DeviceCodeResponse(
            device_code=f"device-{uuid.uuid4()}",
            user_code=user_code,
            verification_uri=f"{github_base_url.rstrip('/')}/login/device",
            verification_uri_complete=f"{github_base_url.rstrip('/')}/login/device?user_code={user_code}",
        )

    def check(self, record: CopilotAuthRecord) -> DeviceCodePollResult:
        index = min(record.poll_count, len(self.poll_results) - 1)
        result = self.poll_results[index]
        if result.status == "authorized" and result.access_token == "gho_mock_source_token":
            return DeviceCodePollResult(
                status="authorized",
                message="authorized",
                access_token=f"gho_mock_source_token_{record.auth_id[-8:]}",
            )
        return result


class CopilotAuthService:
    def __init__(
        self,
        store: MetadataStore,
        client: DeviceCodeClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.client = client or GitHubDeviceCodeClient(app_settings=store.settings)
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    def start(self, *, user: UserRecord, github_base_url: str) -> CopilotAuthRecord:
        response = self.client.start(github_base_url)
        auth_id = str(uuid.uuid4())
        now = self._now()
        record = CopilotAuthRecord(
            auth_id=auth_id,
            user_id=user.id,
            device_code=response.device_code,
            user_code=response.user_code,
            verification_uri=response.verification_uri,
            verification_uri_complete=response.verification_uri_complete,
            expires_in=response.expires_in,
            interval=response.interval,
            github_base_url=GITHUB_COPILOT_OAUTH_BASE_URL,
            created_at=now,
            updated_at=now,
        )
        return self.store.create_copilot_auth(record)

    def check(self, *, user: UserRecord, auth_id: str) -> dict[str, object]:
        record = self.store.get_copilot_auth(auth_id)
        if not record or record.user_id != user.id:
            return {"status": "not_found", "message": "auth_id not found"}
        if self._is_expired(record):
            return {"status": "expired", "message": "expired_token"}

        if self.client.enforce_poll_interval:
            wait_seconds = self._wait_seconds(record)
            if wait_seconds > 0:
                return {
                    "status": "pending",
                    "message": "authorization_pending",
                    "next_poll_after_seconds": wait_seconds,
                }

        result = self.client.check(record)
        record.poll_count += 1
        if result.message == "slow_down":
            record.interval += result.interval_delta_seconds or 5
        record.updated_at = self._now()
        self.store.update_copilot_auth(record)

        if result.status == "pending":
            return {
                "status": "pending",
                "message": result.message,
                "next_poll_after_seconds": record.interval,
            }
        if result.status in {"expired", "declined", "error"}:
            return {"status": result.status, "message": result.message}
        if result.status != "authorized" or not result.access_token:
            return {"status": "error", "message": "authorization_failed"}

        self.store.save_credential(
            user_id=user.id,
            credential_type="github_source_oauth",
            token=result.access_token,
            github_base_url=record.github_base_url,
        )
        return {
            "status": "authorized",
            "token_type": "github_source_oauth",
            "runtime_type": "github_copilot",
            "expires_at": None,
        }

    def _now(self) -> datetime:
        now = self.now_factory()
        return now if now.tzinfo else now.replace(tzinfo=UTC)

    def _is_expired(self, record: CopilotAuthRecord) -> bool:
        return record.created_at + timedelta(seconds=record.expires_in) <= self._now()

    def _wait_seconds(self, record: CopilotAuthRecord) -> int:
        last_poll_at = record.updated_at if record.poll_count > 0 else record.created_at
        next_poll_at = last_poll_at + timedelta(seconds=record.interval)
        return max(0, math.ceil((next_poll_at - self._now()).total_seconds()))
