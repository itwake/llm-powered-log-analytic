from __future__ import annotations

import json
import time

import httpx
import pytest

from app.config import Settings
from app.services.github_copilot_model_gateway import (
    GitHubCopilotCredentials,
    GitHubCopilotModelGateway,
    parse_copilot_api_base_url,
)
from app.services.model_gateway import ModelCredentialError, ModelTransportError

GITHUB_TOKEN = "gho_source_token_1234567890"
COPILOT_TOKEN = "tid=abc;exp=1999999999;proxy-ep=proxy.individual.githubcopilot.com;sku=x"
TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"


def _gateway(handler, token: str = GITHUB_TOKEN) -> tuple[GitHubCopilotModelGateway, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = GitHubCopilotModelGateway(
        credentials=GitHubCopilotCredentials(github_token=token),
        app_settings=Settings(),
        http_client=http_client,
    )
    return gateway, http_client


def test_copilot_api_base_url_is_derived_from_the_session_token() -> None:
    assert parse_copilot_api_base_url(COPILOT_TOKEN) == (
        "https://api.individual.githubcopilot.com"
    )
    assert parse_copilot_api_base_url("tid=abc;exp=1") is None


@pytest.mark.asyncio
async def test_exchanges_github_token_once_and_sends_chat_completion() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == TOKEN_URL:
            assert request.method == "GET"
            assert request.headers["authorization"] == f"Bearer {GITHUB_TOKEN}"
            assert request.headers["editor-version"] == "vscode/1.133.0"
            assert request.headers["copilot-integration-id"] == "vscode-chat"
            return httpx.Response(
                200,
                json={"token": COPILOT_TOKEN, "expires_at": int(time.time()) + 1800},
            )
        assert str(request.url) == "https://api.individual.githubcopilot.com/chat/completions"
        assert request.headers["authorization"] == f"Bearer {COPILOT_TOKEN}"
        assert request.headers["x-initiator"] == "agent"
        assert request.headers["editor-plugin-version"] == "copilot-chat/0.41.0"
        assert json.loads(request.content) == {
            "model": "gpt-5.6-terra",
            "messages": [
                {"role": "developer", "content": "annotate"},
                {"role": "user", "content": [{"type": "text", "text": "gateway 500"}]},
                {"role": "developer", "content": "Return valid JSON only."},
            ],
            "reasoning_effort": "xhigh",
            "response_format": {"type": "json_object"},
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"golden_signal": "error"}'}}]},
        )

    gateway, http_client = _gateway(handler)
    request = dict(
        user_id="user-id",
        model="gpt-5.6-terra",
        instructions="annotate",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "gateway 500"}]}],
        stream=False,
        metadata={"purpose": "template_annotation"},
        reasoning_effort="xhigh",
        response_format={"type": "json_object"},
    )
    first = await gateway.responses(**request)
    second = await gateway.responses(**request)

    assert seen == [
        TOKEN_URL,
        "https://api.individual.githubcopilot.com/chat/completions",
        "https://api.individual.githubcopilot.com/chat/completions",
    ]
    assert first["provider"] == "github_copilot"
    assert first["token_source"] == "github_exchange"
    assert first["output_json"] == {"golden_signal": "error"}
    assert second["output_text"] == first["output_text"]
    await http_client.aclose()


@pytest.mark.asyncio
async def test_prefers_the_api_endpoint_reported_by_the_exchange_and_emulates_streaming() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/copilot_internal/v2/token":
            return httpx.Response(
                200,
                json={
                    "token": "tid=abc",
                    "expires_at": int(time.time()) + 1800,
                    "endpoints": {"api": "https://api.enterprise.githubcopilot.com/"},
                },
            )
        assert str(request.url) == "https://api.enterprise.githubcopilot.com/chat/completions"
        assert request.headers["x-initiator"] == "user"
        assert "stream" not in json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Gateway errors."}}]},
        )

    gateway, http_client = _gateway(handler)
    stream = await gateway.responses(
        user_id="user-id",
        model="gpt-5.4",
        instructions="chat",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        stream=True,
        metadata={"purpose": "case_chat"},
        reasoning_effort="medium",
    )
    events = [event async for event in stream]

    assert [event["type"] for event in events] == ["message.delta", "message.completed"]
    assert events[0]["delta"] == "Gateway errors."
    assert events[-1]["provider"] == "github_copilot"
    assert events[-1]["output_text"] == "Gateway errors."
    await http_client.aclose()


@pytest.mark.asyncio
async def test_refreshes_the_session_after_401_and_redacts_errors() -> None:
    exchanges = 0
    completions = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchanges, completions
        if request.url.path == "/copilot_internal/v2/token":
            exchanges += 1
            return httpx.Response(
                200,
                json={"token": f"session-{exchanges}", "expires_at": int(time.time()) + 1800},
            )
        completions += 1
        if request.headers["authorization"] == "Bearer session-1":
            return httpx.Response(401, json={"message": "token expired"})
        return httpx.Response(400, json={"error": {"message": f"bad model for {GITHUB_TOKEN}"}})

    gateway, http_client = _gateway(handler)
    with pytest.raises(ModelTransportError, match="HTTP 400") as caught:
        await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])

    assert exchanges == 2
    assert completions == 2
    assert GITHUB_TOKEN not in str(caught.value)
    assert "session-2" not in str(caught.value)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_requires_a_connected_github_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    gateway, http_client = _gateway(handler, token="")
    with pytest.raises(ModelCredentialError, match="not connected"):
        await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])
    await http_client.aclose()


@pytest.mark.asyncio
async def test_a_rejected_github_token_is_reported_as_a_credential_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    gateway, http_client = _gateway(handler)
    with pytest.raises(ModelCredentialError, match="reconnect GitHub") as caught:
        await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])

    assert GITHUB_TOKEN not in str(caught.value)
    await http_client.aclose()
