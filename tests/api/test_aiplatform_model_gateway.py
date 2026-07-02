from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.services.aiplatform_model_gateway import AIPlatformModelGateway


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
        app_settings=Settings(
            llm_provider="ai_platform",
            ai_platform_token=trust_token,
            ai_platform_chat_host="https://ai.example",
            ai_platform_chat_uri="/v1/chat",
            ai_platform_usercase="logan-usercase",
            ai_platform_trust_token_header="X-Trust-Token",
            ai_platform_tracking_prefix="LOGAN",
            ai_platform_max_completion_tokens=1234,
        ),
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
    assert response["token_source"] == "env_ai_platform_token"
    assert response["output_text"] == json.dumps(output_json)
    assert response["output_json"] == output_json
    await http_client.aclose()


@pytest.mark.asyncio
async def test_ai_platform_metadata_is_sent_only_when_store_is_enabled() -> None:
    seen_payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        app_settings=Settings(
            llm_provider="ai_platform",
            ai_platform_token="ai-platform-token",
            ai_platform_chat_host="https://chat.example",
            ai_platform_chat_uri="/chat",
            ai_platform_store_completions=True,
        ),
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
        app_settings=Settings(
            llm_provider="ai_platform",
            ai_platform_chat_host="https://chat.example",
            ai_platform_chat_uri="/chat",
            ai_platform_ib2b_host="https://ib2b.example",
            ai_platform_ib2b_uri="/token",
            ai_platform_username="engineer",
            ai_platform_password="secret-password",
            ai_platform_usercase="logan-usercase",
            ai_platform_token_ttl_seconds=60,
        ),
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
        app_settings=Settings(
            llm_provider="ai_platform",
            ai_platform_token="ai-platform-token",
            ai_platform_chat_host="https://chat.example",
            ai_platform_chat_uri="/chat",
        ),
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
