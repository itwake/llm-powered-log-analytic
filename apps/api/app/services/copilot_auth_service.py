from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.store import CopilotAuthRecord, InMemoryStore, UserRecord


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int = 900
    interval: int = 5


class MockGitHubDeviceClient:
    def start(self, github_base_url: str) -> DeviceCodeResponse:
        user_code = "LOGAN-TEST"
        return DeviceCodeResponse(
            device_code=f"device-{uuid.uuid4()}",
            user_code=user_code,
            verification_uri=f"{github_base_url.rstrip('/')}/login/device",
            verification_uri_complete=f"{github_base_url.rstrip('/')}/login/device?user_code={user_code}",
        )

    def check(self, record: CopilotAuthRecord) -> tuple[str, str | None]:
        if record.poll_count == 0:
            return "pending", None
        return "authorized", f"gho_mock_source_token_{record.auth_id[-8:]}"


class CopilotAuthService:
    def __init__(self, store: InMemoryStore, client: MockGitHubDeviceClient | None = None) -> None:
        self.store = store
        self.client = client or MockGitHubDeviceClient()

    def start(self, *, user: UserRecord, github_base_url: str) -> CopilotAuthRecord:
        response = self.client.start(github_base_url)
        auth_id = str(uuid.uuid4())
        record = CopilotAuthRecord(
            auth_id=auth_id,
            user_id=user.id,
            device_code=response.device_code,
            user_code=response.user_code,
            verification_uri=response.verification_uri,
            verification_uri_complete=response.verification_uri_complete,
            expires_in=response.expires_in,
            interval=response.interval,
            github_base_url=github_base_url,
        )
        self.store.copilot_auth[auth_id] = record
        return record

    def check(self, *, user: UserRecord, auth_id: str) -> dict[str, object]:
        record = self.store.copilot_auth.get(auth_id)
        if not record or record.user_id != user.id:
            return {"status": "not_found", "message": "auth_id not found"}
        status, token = self.client.check(record)
        record.poll_count += 1
        if status != "authorized" or token is None:
            return {
                "status": "pending",
                "message": "authorization_pending",
                "next_poll_after_seconds": record.interval,
            }
        self.store.save_credential(
            user_id=user.id,
            credential_type="github_source_oauth",
            token=token,
            github_base_url=record.github_base_url,
        )
        return {
            "status": "authorized",
            "token_type": "github_source_oauth",
            "runtime_type": "github_copilot",
            "expires_at": None,
        }
