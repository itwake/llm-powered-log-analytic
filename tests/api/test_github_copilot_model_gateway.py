from __future__ import annotations

import json
import time

import httpx
import pytest

from app.config import Settings
from app.services.github_copilot_model_gateway import (
    GitHubCopilotModelGateway,
    GitHubCopilotProviderConfig,
    parse_copilot_api_base_url,
)
from app.services.model_gateway import ModelCredentialError, ModelTransportError

GITHUB_TOKEN = "gho_source_token_1234567890"
COPILOT_TOKEN = "tid=abc;exp=1999999999;proxy-ep=proxy.individual.githubcopilot.com;sku=x"


def _gateway(handler, **config) -> tuple[GitHubCopilotModelGateway, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = GitHubCopilotModelGateway(
        config=GitHubCopilotProviderConfig(github_token=GITHUB_TOKEN, **config),
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
async def test_copilot_exchanges_github_token_once_and_sends_chat_completion() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == "https://api.github.com/copilot_internal/v2/token":
            assert request.method == "GET"
            assert request.headers["authorization"] == f"Bearer {GITHUB_TOKEN}"
            assert request.headers["editor-version"] == "vscode/1.133.0"
            assert request.headers["copilot-integration-id"] == "vscode-chat"
            return httpx.Response(
                200,
                json={"token": COPILOT_TOKEN, "expires_at": int(time.time()) + 1800},
            )
        assert str(request.url) == (
            "https://api.individual.githubcopilot.com/chat/completions"
        )
        assert request.headers["authorization"] == f"Bearer {COPILOT_TOKEN}"
        assert request.headers["x-initiator"] == "agent"
        assert request.headers["editor-plugin-version"] == "copilot-chat/0.41.0"
        payload = json.loads(request.content)
        assert payload == {
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
            json={"choices": [{"message": {"content": "{\"golden_signal\": \"error\"}"}}]},
        )

    gateway, http_client = _gateway(handler)
    first = await gateway.responses(
        user_id="user-id",
        model="gpt-5.6-terra",
        instructions="annotate",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "gateway 500"}]}],
        stream=False,
        metadata={"purpose": "template_annotation"},
        reasoning_effort="xhigh",
        response_format={"type": "json_object"},
    )
    second = await gateway.responses(
        user_id="user-id",
        model="gpt-5.6-terra",
        instructions="annotate",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "gateway 500"}]}],
        stream=False,
        metadata={"purpose": "template_annotation"},
        reasoning_effort="xhigh",
        response_format={"type": "json_object"},
    )

    assert [str(request.url) for request in seen] == [
        "https://api.github.com/copilot_internal/v2/token",
        "https://api.individual.githubcopilot.com/chat/completions",
        "https://api.individual.githubcopilot.com/chat/completions",
    ]
    assert first["provider"] == "github_copilot"
    assert first["token_source"] == "github_exchange"
    assert first["output_json"] == {"golden_signal": "error"}
    assert second["output_text"] == first["output_text"]
    await http_client.aclose()


@pytest.mark.asyncio
async def test_copilot_prefers_api_endpoint_from_exchange_and_streams_chat() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
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
        assert request.headers["accept"] == "text/event-stream"
        assert request.headers["x-initiator"] == "user"
        assert json.loads(request.content)["stream"] is True
        body = (
            "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n"
            "data: {\"choices\":[{\"delta\":{\"content\":\"Gateway \"}}]}\n\n"
            ": keep-alive\n\n"
            "data: {\"choices\":[{\"delta\":{\"content\":\"errors.\"}}],\"usage\":{\"total_tokens\":9}}\n\n"
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=body.encode("utf-8"))

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

    assert [event["type"] for event in events] == [
        "message.delta",
        "message.delta",
        "message.completed",
    ]
    assert [event["delta"] for event in events[:2]] == ["Gateway ", "errors."]
    assert events[-1]["output_text"] == "Gateway errors."
    assert events[-1]["provider"] == "github_copilot"
    assert events[-1]["provider_json"]["usage"] == {"total_tokens": 9}
    assert len(seen) == 2
    await http_client.aclose()


@pytest.mark.asyncio
async def test_copilot_refreshes_session_after_401_and_redacts_errors() -> None:
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
        await gateway.responses(user_id="user-id", model="gpt-5.4", instructions=None, input=[])

    assert exchanges == 2
    assert completions == 2
    assert GITHUB_TOKEN not in str(caught.value)
    assert "session-2" not in str(caught.value)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_copilot_requires_a_connected_github_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = GitHubCopilotModelGateway(
        config=GitHubCopilotProviderConfig(github_token=""),
        app_settings=Settings(),
        http_client=http_client,
    )

    with pytest.raises(ModelCredentialError, match="not connected"):
        await gateway.responses(user_id="user-id", model="gpt-5.4", instructions=None, input=[])
    await http_client.aclose()


@pytest.mark.asyncio
async def test_copilot_rejected_github_token_is_reported_as_credential_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    gateway, http_client = _gateway(handler)
    with pytest.raises(ModelCredentialError, match="reconnect GitHub") as caught:
        await gateway.responses(user_id="user-id", model="gpt-5.4", instructions=None, input=[])

    assert GITHUB_TOKEN not in str(caught.value)
    await http_client.aclose()
