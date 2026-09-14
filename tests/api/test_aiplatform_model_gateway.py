from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.services.aiplatform_model_gateway import (
    AIPlatformCredentials,
    AIPlatformModelGateway,
)
from app.services.model_gateway import ModelCredentialError

CREDENTIALS = AIPlatformCredentials(
    username="engineer",
    usercase="logan-usercase",
    password="secret-password",
)
EXCHANGE_URL = "https://ib2b.example/token"
CHAT_URL = "https://chat.example/chat"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ai_platform_chat_host": "https://chat.example",
        "ai_platform_chat_uri": "/chat",
        "ai_platform_ib2b_host": "https://ib2b.example",
        "ai_platform_ib2b_uri": "/token",
        "ai_platform_token_ttl_seconds": 60,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _gateway(
    handler,
    *,
    credentials: AIPlatformCredentials = CREDENTIALS,
    **settings_overrides: object,
) -> tuple[AIPlatformModelGateway, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = AIPlatformModelGateway(
        credentials=credentials,
        app_settings=_settings(**settings_overrides),
        http_client=http_client,
    )
    return gateway, http_client


@pytest.mark.asyncio
async def test_ib2b_exchange_then_chat_payload_and_output_parsing() -> None:
    output_json = {"summary": "Gateway errors increased.", "confidence": 0.91}
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == EXCHANGE_URL:
            assert json.loads(request.content) == {
                "input_token_state": {
                    "token_type": "CREDENTIAL",
                    "username": "engineer",
                    "password": "secret-password",
                },
                "output_token_state": {"token_type": "JWT"},
            }
            return httpx.Response(200, json={"issued_token": "issued-jwt"})

        assert str(request.url) == CHAT_URL
        assert request.headers["x-trust-token"] == "issued-jwt"
        assert request.headers["x-correlation-id"].startswith("LOGAN-")
        assert request.headers["x-usersession-id"] == request.headers["x-correlation-id"]
        assert json.loads(request.content) == {
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

    gateway, http_client = _gateway(
        handler,
        ai_platform_max_completion_tokens=1234,
        ai_platform_trust_token_header="X-Trust-Token",
        ai_platform_tracking_prefix="LOGAN",
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

    assert seen == [EXCHANGE_URL, CHAT_URL]
    assert response["provider"] == "ai_platform"
    assert response["token_source"] == "ib2b_exchange"
    assert response["output_json"] == output_json
    await http_client.aclose()


@pytest.mark.asyncio
async def test_exchanged_token_is_reused_for_a_second_response() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == EXCHANGE_URL:
            return httpx.Response(200, json={"issued_token": "issued-jwt"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    gateway, http_client = _gateway(handler)
    first = await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])
    second = await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])

    assert seen == [EXCHANGE_URL, CHAT_URL, CHAT_URL]
    assert first["output_text"] == "ok"
    assert second["token_source"] == "ib2b_exchange"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_json_response_format_reuses_an_existing_json_instruction() -> None:
    payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == EXCHANGE_URL:
            return httpx.Response(200, json={"issued_token": "issued-jwt"})
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    gateway, http_client = _gateway(handler)
    await gateway.responses(
        user_id="u",
        model="gpt-5.4",
        instructions="Return valid JSON only.",
        input=[],
        response_format={"type": "json_object"},
    )

    assert payloads[0]["messages"] == [
        {"role": "developer", "content": "Return valid JSON only."}
    ]
    await http_client.aclose()


@pytest.mark.asyncio
async def test_metadata_is_sent_only_when_store_is_enabled() -> None:
    payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == EXCHANGE_URL:
            return httpx.Response(200, json={"issued_token": "issued-jwt"})
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    gateway, http_client = _gateway(handler, ai_platform_store_completions=True)
    await gateway.responses(
        user_id="u",
        model="gpt-5.4",
        instructions=None,
        input=[],
        metadata={"case_id": "case-1", "purpose": "case_chat"},
    )

    assert payloads == [
        {
            "model": "gpt-5.4",
            "messages": [],
            "reasoning_effort": "high",
            "max_completion_tokens": 4096,
            "user": "logan-usercase",
            "store": True,
            "metadata": {"case_id": "case-1", "purpose": "case_chat"},
        }
    ]
    await http_client.aclose()


@pytest.mark.asyncio
async def test_streaming_is_emulated_from_the_chat_completion_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == EXCHANGE_URL:
            return httpx.Response(200, json={"issued_token": "issued-jwt"})
        assert "stream" not in json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "streamed enough"}}]},
        )

    gateway, http_client = _gateway(handler)
    stream = await gateway.responses(
        user_id="u",
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
async def test_concurrent_requests_share_one_token_exchange() -> None:
    """Template annotation fires up to eight requests at once on one gateway."""
    exchanges = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchanges
        if str(request.url) == EXCHANGE_URL:
            exchanges += 1
            await asyncio.sleep(0)  # let the other requests reach the exchange
            return httpx.Response(200, json={"issued_token": "issued-jwt"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    gateway, http_client = _gateway(handler)
    results = await asyncio.gather(
        *(
            gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])
            for _ in range(8)
        )
    )

    assert exchanges == 1
    assert [result["output_text"] for result in results] == ["ok"] * 8
    await http_client.aclose()


@pytest.mark.asyncio
async def test_blank_header_settings_fall_back_to_the_defaults() -> None:
    """A blank header name is an illegal HTTP header; the defaults must apply instead."""
    headers: list[httpx.Headers] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == EXCHANGE_URL:
            return httpx.Response(200, json={"issued_token": "issued-jwt"})
        headers.append(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    gateway, http_client = _gateway(
        handler,
        ai_platform_trust_token_header="  ",
        ai_platform_tracking_prefix=" ",
    )
    await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])

    assert headers[0]["X-XXXX-E2E-Trust-Token"] == "issued-jwt"
    assert headers[0]["x-correlation-id"].startswith("EFP-")
    await http_client.aclose()


@pytest.mark.asyncio
async def test_http_errors_are_redacted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == EXCHANGE_URL:
            return httpx.Response(200, json={"issued_token": "issued-jwt"})
        return httpx.Response(
            403,
            json={"error": {"message": "denied for Bearer leaked-secret-token"}},
        )

    gateway, http_client = _gateway(handler)
    with pytest.raises(Exception, match="HTTP 403") as caught:
        await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])

    assert "leaked-secret-token" not in str(caught.value)
    assert "issued-jwt" not in str(caught.value)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_incomplete_credentials_are_reported_before_any_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    gateway, http_client = _gateway(
        handler,
        credentials=AIPlatformCredentials(username="engineer", usercase="logan"),
    )

    with pytest.raises(ModelCredentialError, match="missing credentials"):
        await gateway.responses(user_id="u", model="gpt-5.4", instructions=None, input=[])
    await http_client.aclose()


def test_credentials_come_from_the_provider_record_without_leaking_the_password() -> None:
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
        created_at=now,
        updated_at=now,
        secrets={"password": "secret"},
    )
    credentials = AIPlatformCredentials.from_provider(provider)

    assert credentials.username == "engineer"
    assert credentials.usercase == "logan"
    assert credentials.configured
    assert "secret" not in repr(credentials)
