from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.services.aiplatform_model_gateway import (
    AIPlatformModelGateway,
    AIPlatformProviderConfig,
)


@pytest.mark.asyncio
async def test_ai_platform_token_chat_payload_and_output_parsing() -> None:
    trust_token = "ai-platform-trust-token"
    output_json = {"summary": "Gateway errors increased.", "confidence": 0.91}
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://ai.example/v1/chat"
        assert request.headers["x-trust-token"] == trust_token
        assert request.headers["x-correlation-id"].startswith("LOGAN-")
        assert request.headers["x-usersession-id"] == request.headers["x-correlation-id"]
        payload = json.loads(request.content)
        assert payload == {
            "model": "gpt-5.4",
            "messages": [
                {"role": "developer", "content": "template_annotation"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "gateway 500"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,abc"},
                        },
                    ],
                },
                {"role": "developer", "content": "Return valid JSON only."},
            ],
            "reasoning_effort": "high",
            "max_completion_tokens": 1234,
            "user": "logan-usercase",
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output_json)}}]},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        config=AIPlatformProviderConfig(
            chat_host="https://ai.example",
            chat_uri="/v1/chat",
            usercase="logan-usercase",
            trust_token_header="X-Trust-Token",
            tracking_prefix="LOGAN",
            token=trust_token,
        ),
        app_settings=Settings(ai_platform_max_completion_tokens=1234),
        http_client=http_client,
    )

    response = await gateway.responses(
        user_id="user-id",
        model="gpt-5.4",
        instructions="template_annotation",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "gateway 500"},
                    {"type": "input_image", "image_url": "data:image/png;base64,abc"},
                ],
            }
        ],
        stream=False,
        metadata={"case_id": "case-1"},
        reasoning_effort="high",
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    assert len(seen) == 1
    assert response["provider"] == "ai_platform"
    assert response["token_source"] == "provider_token"
    assert response["output_text"] == json.dumps(output_json)
    assert response["output_json"] == output_json
    await http_client.aclose()


@pytest.mark.asyncio
async def test_ai_platform_json_response_format_reuses_existing_json_instruction() -> None:
    seen_payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        config=AIPlatformProviderConfig(
            chat_host="https://chat.example",
            chat_uri="/chat",
            token="ai-platform-token",
        ),
        app_settings=Settings(),
        http_client=http_client,
    )

    await gateway.responses(
        user_id="user-id",
        model="gpt-5.4",
        instructions="Return valid JSON only.",
        input=[],
        response_format={"type": "json_object"},
    )

    assert seen_payloads[0]["messages"] == [
        {"role": "developer", "content": "Return valid JSON only."}
    ]
    await http_client.aclose()


@pytest.mark.asyncio
async def test_ai_platform_metadata_is_sent_only_when_store_is_enabled() -> None:
    seen_payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        config=AIPlatformProviderConfig(
            chat_host="https://chat.example",
            chat_uri="/chat",
            token="ai-platform-token",
        ),
        app_settings=Settings(ai_platform_store_completions=True),
        http_client=http_client,
    )

    await gateway.responses(
        user_id="user-id",
        model="gpt-5.4",
        instructions=None,
        input=[],
        metadata={"case_id": "case-1", "purpose": "case_chat"},
    )

    assert seen_payloads == [
        {
            "model": "gpt-5.4",
            "messages": [],
            "reasoning_effort": "high",
            "max_completion_tokens": 4096,
            "store": True,
            "metadata": {"case_id": "case-1", "purpose": "case_chat"},
        }
    ]
    await http_client.aclose()


@pytest.mark.asyncio
async def test_ai_platform_exchanges_ib2b_token_and_caches_for_second_response() -> None:
    exchanged_token = "issued-ai-platform-jwt"
    seen_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if str(request.url) == "https://ib2b.example/token":
            payload = json.loads(request.content)
            assert payload == {
                "input_token_state": {
                    "token_type": "CREDENTIAL",
                    "username": "engineer",
                    "password": "secret-password",
                },
                "output_token_state": {"token_type": "JWT"},
            }
            return httpx.Response(200, json={"issued_token": exchanged_token})

        assert str(request.url) == "https://chat.example/chat"
        assert request.headers["x-xxxx-e2e-trust-token"] == exchanged_token
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        config=AIPlatformProviderConfig(
            chat_host="https://chat.example",
            chat_uri="/chat",
            ib2b_host="https://ib2b.example",
            ib2b_uri="/token",
            username="engineer",
            password="secret-password",
            usercase="logan-usercase",
        ),
        app_settings=Settings(ai_platform_token_ttl_seconds=60),
        http_client=http_client,
    )

    first = await gateway.responses(user_id="user-id", model="gpt-5.4", instructions=None, input=[])
    second = await gateway.responses(user_id="user-id", model="gpt-5.4", instructions=None, input=[])

    assert seen_urls == [
        "https://ib2b.example/token",
        "https://chat.example/chat",
        "https://chat.example/chat",
    ]
    assert first["token_source"] == "ib2b_exchange"
    assert second["token_source"] == "ib2b_exchange"
    assert first["output_text"] == "ok"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_ai_platform_streaming_is_emulated_from_chat_completion_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "stream" not in payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "streamed enough"}}]},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        config=AIPlatformProviderConfig(
            chat_host="https://chat.example",
            chat_uri="/chat",
            token="ai-platform-token",
        ),
        app_settings=Settings(),
        http_client=http_client,
    )

    stream = await gateway.responses(
        user_id="user-id",
        model="gpt-5.4",
        instructions="case_chat",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
        stream=True,
    )
    events = [event async for event in stream]

    assert [event["type"] for event in events] == ["message.delta", "message.completed"]
    assert events[0]["delta"] == "streamed enough"
    assert events[-1]["provider"] == "ai_platform"
    assert events[-1]["output_text"] == "streamed enough"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_ai_platform_http_errors_are_redacted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "denied for Bearer leaked-secret-token"}},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        config=AIPlatformProviderConfig(
            chat_host="https://chat.example",
            chat_uri="/chat",
            token="ai-platform-token",
        ),
        app_settings=Settings(),
        http_client=http_client,
    )

    with pytest.raises(Exception, match="HTTP 403") as caught:
        await gateway.responses(user_id="user-id", model="gpt-5.4", instructions=None, input=[])

    assert "leaked-secret-token" not in str(caught.value)
    assert "ai-platform-token" not in str(caught.value)
    await http_client.aclose()


def test_ai_platform_config_falls_back_to_deployment_defaults() -> None:
    from datetime import UTC, datetime

    from app.records import LlmProviderRecord

    now = datetime.now(UTC)
    provider = LlmProviderRecord(
        id="p1",
        user_id="u1",
        name="Corp AI",
        provider_type="ai_platform",
        config={"username": "engineer", "usercase": "logan"},
        models=["gpt-5.4"],
        default_model="gpt-5.4",
        default_reasoning_effort="high",
        is_default=True,
        created_at=now,
        updated_at=now,
        secrets={"password": "secret"},
    )
    config = AIPlatformProviderConfig.from_provider(
        provider,
        Settings(
            ai_platform_chat_host="https://ai.example.test",
            ai_platform_ib2b_host="https://identity.example.test",
        ),
    )

    assert config.chat_host == "https://ai.example.test"
    assert config.chat_uri == "/v1/api/v1/chat/completions"
    assert config.ib2b_host == "https://identity.example.test"
    assert config.exchange_credentials_configured
    assert config.credentials_configured
    assert "secret" not in repr(config)
