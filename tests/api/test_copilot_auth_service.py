from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings
from app.core.security import decrypt_token
from app.services.copilot_auth_service import (
    DEVICE_CODE_GRANT_TYPE,
    GITHUB_COPILOT_OAUTH_BASE_URL,
    DeviceCodePollResult,
    GitHubDeviceCodeClient,
    MockGitHubDeviceClient,
    CopilotAuthService,
)
from app.store import CopilotAuthRecord, InMemoryStore


def _user(store: InMemoryStore):
    return store.register_user(
        email="auth.engineer@example.com",
        username="auth-engineer",
        full_name="Auth Engineer",
        password="password123",
    )


def test_device_code_start_success_uses_github_payload_and_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://github.com/login/device/code"
        assert json.loads(request.content) == {
            "client_id": "Iv1.b507a08c87ecfe98",
            "scope": "read:user",
        }
        assert request.headers["accept"] == "application/json"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["user-agent"] == "GitHubCopilotChat/0.35.0"
        return httpx.Response(
            200,
            json={
                "device_code": "device-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "verification_uri_complete": "https://github.com/login/device?user_code=ABCD-EFGH",
                "expires_in": 900,
                "interval": 5,
            },
        )

    client = GitHubDeviceCodeClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    response = client.start("https://github.com")

    assert len(requests) == 1
    assert response.device_code == "device-code-1"
    assert response.user_code == "ABCD-EFGH"
    assert response.interval == 5


def test_device_code_client_uses_configured_copilot_ca_bundle(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "app.services.copilot_auth_service.httpx.Client",
        CapturingClient,
    )

    GitHubDeviceCodeClient(
        app_settings=Settings(
            copilot_ca_bundle="/etc/ssl/corp-root-ca.pem",
            copilot_proxy_url="http://proxy.example:8080",
        )
    )

    assert captured["verify"] == "/etc/ssl/corp-root-ca.pem"
    assert captured["proxy"] == "http://proxy.example:8080"
    assert captured["trust_env"] is True


def test_device_code_start_ignores_request_base_url() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "device_code": "device-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
            },
        )

    client = GitHubDeviceCodeClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    client.start("https://evil.example")

    assert [str(request.url) for request in requests] == [
        "https://github.com/login/device/code"
    ]


def test_device_code_poll_pending_uses_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://github.com/login/oauth/access_token"
        assert json.loads(request.content) == {
            "client_id": "Iv1.b507a08c87ecfe98",
            "device_code": "device-code-1",
            "grant_type": DEVICE_CODE_GRANT_TYPE,
        }
        assert request.headers["accept"] == "application/json"
        assert request.headers["user-agent"] == "GitHubCopilotChat/0.35.0"
        return httpx.Response(200, json={"error": "authorization_pending"})

    client = GitHubDeviceCodeClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.check(_auth_record())

    assert result.status == "pending"
    assert result.message == "authorization_pending"


def test_device_code_poll_ignores_record_base_url() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"error": "authorization_pending"})

    client = GitHubDeviceCodeClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.check(_auth_record(github_base_url="https://evil.example"))

    assert result.status == "pending"
    assert [str(request.url) for request in requests] == [
        "https://github.com/login/oauth/access_token"
    ]


def test_device_code_poll_slow_down_updates_service_interval() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/login/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 5,
                },
            )
        return httpx.Response(200, json={"error": "slow_down"})

    store = InMemoryStore()
    user = _user(store)
    client = GitHubDeviceCodeClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    current_time = [datetime(2026, 6, 6, 10, 0, tzinfo=UTC)]
    service = CopilotAuthService(store, client=client, now_factory=lambda: current_time[0])
    record = service.start(user=user, github_base_url="https://github.com")
    current_time[0] += timedelta(seconds=record.interval)

    response = service.check(user=user, auth_id=record.auth_id)

    assert calls == 2
    assert response == {
        "status": "pending",
        "message": "slow_down",
        "next_poll_after_seconds": 10,
    }
    assert store.get_copilot_auth(record.auth_id).interval == 10  # type: ignore[union-attr]


def test_service_stores_public_github_base_url_for_arbitrary_start_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "device_code": "device-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "verification_uri_complete": "https://github.com/login/device?user_code=ABCD-EFGH",
                "expires_in": 900,
                "interval": 5,
            },
        )

    store = InMemoryStore()
    user = _user(store)
    client = GitHubDeviceCodeClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    service = CopilotAuthService(store, client=client)

    record = service.start(user=user, github_base_url="https://evil.example")

    assert record.github_base_url == GITHUB_COPILOT_OAUTH_BASE_URL
    stored = store.get_copilot_auth(record.auth_id)
    assert stored is not None
    assert stored.github_base_url == GITHUB_COPILOT_OAUTH_BASE_URL


def test_device_code_authorized_stores_encrypted_token_and_returns_no_token() -> None:
    source_token = "gho_sensitive_source_token"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://github.com/login/device",
                    "verification_uri_complete": "https://github.com/login/device?user_code=ABCD-EFGH",
                    "expires_in": 900,
                    "interval": 5,
                },
            )
        return httpx.Response(200, json={"access_token": source_token, "token_type": "bearer"})

    store = InMemoryStore()
    user = _user(store)
    client = GitHubDeviceCodeClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    current_time = [datetime(2026, 6, 6, 10, 0, tzinfo=UTC)]
    service = CopilotAuthService(store, client=client, now_factory=lambda: current_time[0])
    record = service.start(user=user, github_base_url="https://github.com")
    current_time[0] += timedelta(seconds=record.interval)

    response = service.check(user=user, auth_id=record.auth_id)

    assert response == {
        "status": "authorized",
        "token_type": "github_source_oauth",
        "runtime_type": "github_copilot",
        "expires_at": None,
    }
    assert source_token not in json.dumps(response)
    credential = store.get_credential(user_id=user.id, credential_type="github_source_oauth")
    assert credential is not None
    assert source_token.encode() not in credential.encrypted_token
    assert (
        decrypt_token(credential.encrypted_token, store.settings.credential_encryption_key)
        == source_token
    )


def test_device_code_declined_expired_and_not_found() -> None:
    def poll_result(github_error: str) -> str:
        client = GitHubDeviceCodeClient(
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(200, json={"error": github_error})
                )
            )
        )
        return client.check(_auth_record()).status

    assert poll_result("access_denied") == "declined"
    assert poll_result("authorization_declined") == "declined"
    assert poll_result("expired_token") == "expired"

    store = InMemoryStore()
    user = _user(store)
    response = CopilotAuthService(store, client=MockGitHubDeviceClient()).check(
        user=user, auth_id="missing-auth-id"
    )
    assert response == {"status": "not_found", "message": "auth_id not found"}


def test_service_respects_interval_before_polling_real_client() -> None:
    store = InMemoryStore()
    user = _user(store)
    calls = 0
    now = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)

    class IntervalClient(MockGitHubDeviceClient):
        enforce_poll_interval = True

        def check(self, record: CopilotAuthRecord) -> DeviceCodePollResult:
            nonlocal calls
            calls += 1
            return super().check(record)

    service = CopilotAuthService(
        store,
        client=IntervalClient(
            [DeviceCodePollResult(status="pending", message="authorization_pending")]
        ),
        now_factory=lambda: now,
    )
    record = service.start(user=user, github_base_url="https://github.com")

    response = service.check(user=user, auth_id=record.auth_id)

    assert response == {
        "status": "pending",
        "message": "authorization_pending",
        "next_poll_after_seconds": 5,
    }
    assert calls == 0


def _auth_record(github_base_url: str = GITHUB_COPILOT_OAUTH_BASE_URL) -> CopilotAuthRecord:
    now = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    return CopilotAuthRecord(
        auth_id="auth-id-1",
        user_id="user-id-1",
        device_code="device-code-1",
        user_code="ABCD-EFGH",
        verification_uri="https://github.com/login/device",
        verification_uri_complete="https://github.com/login/device?user_code=ABCD-EFGH",
        expires_in=900,
        interval=5,
        github_base_url=github_base_url,
        created_at=now,
        updated_at=now,
    )
