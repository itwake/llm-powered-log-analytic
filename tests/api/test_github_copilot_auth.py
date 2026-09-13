from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.services.github_copilot_auth import COPILOT_OAUTH_CLIENT_ID, GitHubDeviceFlow
from app.services.model_gateway import ModelTransportError


def _device_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "device_code": "device-secret",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
    )


@pytest.mark.asyncio
async def test_device_flow_start_then_pending_then_authorized() -> None:
    token_polls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_polls
        if request.url.path == "/login/device/code":
            assert json.loads(request.content) == {
                "client_id": COPILOT_OAUTH_CLIENT_ID,
                "scope": "read:user",
            }
            return _device_response()
        if request.url.path == "/login/oauth/access_token":
            token_polls += 1
            assert json.loads(request.content)["device_code"] == "device-secret"
            if token_polls == 1:
                return httpx.Response(200, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "gho_new_token", "token_type": "bearer"})
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer gho_new_token"
            return httpx.Response(200, json={"login": "octocat"})
        raise AssertionError(str(request.url))

    flow = GitHubDeviceFlow(
        app_settings=Settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    pending = await flow.start(user_id="user-1", provider_id="provider-1")
    assert pending.user_code == "ABCD-1234"
    assert pending.verification_uri_complete == "https://github.com/login/device"
    assert 0 < pending.expires_in <= 900
    assert "device-secret" not in repr(pending)

    first = await flow.check(user_id="user-1", auth_id=pending.auth_id)
    assert first.status == "pending"
    throttled = await flow.check(user_id="user-1", auth_id=pending.auth_id)
    assert throttled.status == "pending"
    assert token_polls == 1

    pending.last_polled_at = None
    authorized = await flow.check(user_id="user-1", auth_id=pending.auth_id)
    assert authorized.status == "authorized"
    assert authorized.access_token == "gho_new_token"
    assert authorized.github_login == "octocat"
    assert "gho_new_token" not in repr(authorized)
    assert flow.pending_for(user_id="user-1", auth_id=pending.auth_id) is None
    await flow.aclose()


@pytest.mark.asyncio
async def test_device_flow_is_scoped_to_the_requesting_user() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/device/code":
            return _device_response()
        raise AssertionError("token endpoint must not be polled for another user")

    flow = GitHubDeviceFlow(
        app_settings=Settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    pending = await flow.start(user_id="user-1", provider_id="provider-1")

    result = await flow.check(user_id="user-2", auth_id=pending.auth_id)

    assert result.status == "expired"
    await flow.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("expired_token", "expired"),
        ("access_denied", "declined"),
        ("incorrect_device_code", "failed"),
    ],
)
async def test_device_flow_reports_github_errors(error: str, expected: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/device/code":
            return _device_response()
        return httpx.Response(200, json={"error": error, "error_description": "nope"})

    flow = GitHubDeviceFlow(
        app_settings=Settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    pending = await flow.start(user_id="user-1", provider_id="provider-1")

    result = await flow.check(user_id="user-1", auth_id=pending.auth_id)

    assert result.status == expected
    assert result.access_token is None
    await flow.aclose()


@pytest.mark.asyncio
async def test_device_flow_start_failure_is_a_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="github unavailable")

    flow = GitHubDeviceFlow(
        app_settings=Settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ModelTransportError, match="HTTP 503"):
        await flow.start(user_id="user-1", provider_id="provider-1")
    await flow.aclose()
