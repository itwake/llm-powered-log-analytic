from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import Settings
from app.core.security import decrypt_token
from app.observability import metrics_text
from app.services.copilot_model_gateway import (
    COPILOT_TOKEN_EXCHANGE_URL,
    CopilotCredentialError,
    CopilotModelGateway,
    CopilotTransportError,
)
from app.store import InMemoryStore


def _store_and_user() -> tuple[InMemoryStore, str]:
    store = InMemoryStore()
    user = store.register_user(
        email="gateway.engineer@example.com",
        username="gateway-engineer",
        full_name="Gateway Engineer",
        password="password123",
    )
    return store, user.id


def test_model_gateway_uses_configured_copilot_tls_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturingAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "app.services.copilot_model_gateway.httpx.AsyncClient",
        CapturingAsyncClient,
    )

    CopilotModelGateway(
        app_settings=Settings(
            copilot_tls_verify=False,
            copilot_proxy_url="http://proxy.example:8080",
            copilot_trust_env=False,
        )
    )

    assert captured["verify"] is False
    assert captured["proxy"] == "http://proxy.example:8080"
    assert captured["trust_env"] is False


@pytest.mark.asyncio
async def test_source_token_exchange_proxy_base_responses_payload_and_output_parsing() -> None:
    store, user_id = _store_and_user()
    source_token = "gho_source_token_for_exchange"
    copilot_token = "copilot-session;proxy-ep=https://proxy.individual.githubcopilot.com;exp=1"
    output_json = {
        "golden_signal": "error",
        "fault_categories": ["application"],
        "entities": {"service": ["gateway"]},
        "severity_score": 0.8,
        "confidence": 0.9,
        "rationale": "Gateway returned 500 errors.",
    }
    seen: list[httpx.Request] = []
    store.save_credential(
        user_id=user_id,
        credential_type="github_source_oauth",
        token=source_token,
        github_base_url="https://github.com",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            assert str(request.url) == COPILOT_TOKEN_EXCHANGE_URL
            assert request.headers["authorization"] == f"Bearer {source_token}"
            assert request.headers["accept"] == "application/json"
            assert request.headers["user-agent"] == "GitHubCopilotChat/0.35.0"
            assert request.headers["editor-version"] == "vscode/1.107.0"
            assert request.headers["editor-plugin-version"] == "copilot-chat/0.35.0"
            assert request.headers["copilot-integration-id"] == "vscode-chat"
            return httpx.Response(200, json={"token": copilot_token, "expires_at": 9999999999})

        assert request.method == "POST"
        assert str(request.url) == "https://api.individual.githubcopilot.com/responses"
        assert request.headers["authorization"] == f"Bearer {copilot_token}"
        assert request.headers["accept"] == "application/vnd.github.copilot-chat-preview+json"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["openai-intent"] == "conversation-edits"
        assert request.headers["x-initiator"] == "agent"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-5.4"
        assert payload["instructions"] == "template_annotation"
        assert payload["stream"] is False
        assert payload["reasoning"] == {"effort": "high"}
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(output_json)}],
                    }
                ],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(store=store, http_client=http_client)

    response = await gateway.responses(
        user_id=user_id,
        model="gpt-5.4",
        instructions="template_annotation",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "gateway 500"}]}],
        stream=False,
        metadata={"case_id": "case-1"},
        reasoning_effort="high",
        response_format={"type": "json_object"},
    )

    assert [request.method for request in seen] == ["GET", "POST"]
    assert response["provider"] == "github_copilot"
    assert response["token_source"] == "stored_github_source_oauth"
    assert response["output_text"] == json.dumps(output_json)
    assert response["output_json"] == output_json
    cached = store.get_credential(user_id=user_id, credential_type="copilot_plugin_token")
    assert cached is not None
    assert cached.expires_at == datetime.fromtimestamp(9999999999, UTC)
    assert (
        decrypt_token(cached.encrypted_token, store.settings.credential_encryption_key)
        == copilot_token
    )
    body = metrics_text()
    assert (
        'logan_copilot_gateway_requests_total{model="gpt-5.4",provider="github_copilot",'
        'status="succeeded",stream="false"}'
    ) in body
    assert source_token not in body
    assert copilot_token not in body
    await http_client.aclose()


@pytest.mark.asyncio
async def test_source_token_exchange_caches_plugin_token_for_second_response() -> None:
    store, user_id = _store_and_user()
    source_token = "gho_source_token_for_cache"
    copilot_token = "cached-copilot-plugin-token"
    exchange_calls = 0
    response_tokens: list[str] = []
    store.save_credential(
        user_id=user_id,
        credential_type="github_source_oauth",
        token=source_token,
        github_base_url="https://github.com",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchange_calls
        if request.method == "GET":
            exchange_calls += 1
            assert request.headers["authorization"] == f"Bearer {source_token}"
            return httpx.Response(
                200,
                json={"token": copilot_token, "expires_at": "2035-01-01T00:00:00Z"},
            )

        assert request.method == "POST"
        response_tokens.append(request.headers["authorization"])
        return httpx.Response(200, json={"output_text": f"response-{len(response_tokens)}"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(store=store, http_client=http_client)

    first = await gateway.responses(user_id=user_id, model="gpt-5.4", instructions=None, input=[])
    second = await gateway.responses(user_id=user_id, model="gpt-5.4", instructions=None, input=[])

    assert first["token_source"] == "stored_github_source_oauth"
    assert second["token_source"] == "stored_copilot_plugin_token"
    assert exchange_calls == 1
    assert response_tokens == [f"Bearer {copilot_token}", f"Bearer {copilot_token}"]
    cached = store.get_credential(user_id=user_id, credential_type="copilot_plugin_token")
    assert cached is not None
    assert cached.expires_at == datetime(2035, 1, 1, tzinfo=UTC)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_expired_plugin_token_is_ignored_and_refreshed_from_source() -> None:
    store, user_id = _store_and_user()
    source_token = "gho_source_token_for_refresh"
    expired_plugin_token = "expired-copilot-plugin-token"
    refreshed_plugin_token = "refreshed-copilot-plugin-token"
    seen_methods: list[str] = []
    store.save_credential(
        user_id=user_id,
        credential_type="github_source_oauth",
        token=source_token,
        github_base_url="https://github.com",
    )
    store.save_credential(
        user_id=user_id,
        credential_type="copilot_plugin_token",
        token=expired_plugin_token,
        github_base_url="https://github.com",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_methods.append(request.method)
        if request.method == "GET":
            assert request.headers["authorization"] == f"Bearer {source_token}"
            return httpx.Response(
                200,
                json={"token": refreshed_plugin_token, "expires_at": 32503680000},
            )

        assert request.method == "POST"
        assert request.headers["authorization"] == f"Bearer {refreshed_plugin_token}"
        return httpx.Response(200, json={"output_text": "refreshed response"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(store=store, http_client=http_client)

    response = await gateway.responses(
        user_id=user_id,
        model="gpt-5.4",
        instructions=None,
        input=[],
    )

    assert seen_methods == ["GET", "POST"]
    assert response["token_source"] == "stored_github_source_oauth"
    cached = store.get_credential(user_id=user_id, credential_type="copilot_plugin_token")
    assert cached is not None
    assert (
        decrypt_token(cached.encrypted_token, store.settings.credential_encryption_key)
        == refreshed_plugin_token
    )
    await http_client.aclose()


@pytest.mark.asyncio
async def test_stored_plugin_token_path_does_not_exchange_and_takes_precedence() -> None:
    store, user_id = _store_and_user()
    plugin_token = "copilot-direct-token"
    store.save_credential(
        user_id=user_id,
        credential_type="github_source_oauth",
        token="gho_source_token_that_should_not_be_used",
        github_base_url="https://github.com",
    )
    store.save_credential(
        user_id=user_id,
        credential_type="copilot_plugin_token",
        token=plugin_token,
        github_base_url="https://github.com",
    )
    seen_methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_methods.append(request.method)
        assert request.method == "POST"
        assert str(request.url) == "https://api.githubcopilot.com/responses"
        assert request.headers["authorization"] == f"Bearer {plugin_token}"
        return httpx.Response(200, json={"output_text": "direct plugin response"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(store=store, http_client=http_client)

    response = await gateway.responses(
        user_id=user_id,
        model="gpt-5.4",
        instructions=None,
        input=[],
    )

    assert seen_methods == ["POST"]
    assert response["token_source"] == "stored_copilot_plugin_token"
    assert response["output_text"] == "direct plugin response"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_environment_copilot_token_fallback() -> None:
    plugin_token = "env-copilot-plugin-token"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["authorization"] == f"Bearer {plugin_token}"
        return httpx.Response(200, json={"choices": [{"message": {"content": "env response"}}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(
        app_settings=Settings(github_copilot_token=plugin_token),
        http_client=http_client,
    )

    response = await gateway.responses(user_id="user-id", model="gpt-5.4", instructions=None, input=[])

    assert response["token_source"] == "env_github_copilot_token"
    assert response["output_text"] == "env response"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_streaming_responses_parse_sse_deltas_and_send_stream_headers() -> None:
    store, user_id = _store_and_user()
    plugin_token = "streaming-copilot-plugin-token"
    store.save_credential(
        user_id=user_id,
        credential_type="copilot_plugin_token",
        token=plugin_token,
        github_base_url="https://github.com",
    )
    seen_payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.githubcopilot.com/responses"
        assert request.headers["authorization"] == f"Bearer {plugin_token}"
        assert request.headers["accept"] == "text/event-stream"
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["metadata"] == {"case_id": "case-1"}
        seen_payloads.append(payload)
        return httpx.Response(
            200,
            content=(
                'data: {"type":"response.output_text.delta","delta":"Hello "}\n\n'
                'data: {"type":"output_text_delta","delta":"from "}\n\n'
                'data: {"choices":[{"delta":{"content":"Copilot"}}]}\n\n'
                'data: {"type":"response.completed","response":{"id":"resp_1","output_text":"Hello from Copilot"}}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(store=store, http_client=http_client)

    stream = await gateway.responses(
        user_id=user_id,
        model="gpt-5.4",
        instructions="case_chat",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
        stream=True,
        metadata={"case_id": "case-1"},
    )
    events = [event async for event in stream]

    assert len(seen_payloads) == 1
    assert [event["type"] for event in events] == [
        "message.delta",
        "message.delta",
        "message.delta",
        "message.completed",
    ]
    assert "".join(event["delta"] for event in events if event["type"] == "message.delta") == (
        "Hello from Copilot"
    )
    assert events[-1]["output_text"] == "Hello from Copilot"
    assert events[-1]["provider_json"]["id"] == "resp_1"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_response_transport_errors_redact_plugin_token() -> None:
    store, user_id = _store_and_user()
    plugin_token = "copilot-secret-token"
    store.save_credential(
        user_id=user_id,
        credential_type="copilot_plugin_token",
        token=plugin_token,
        github_base_url="https://github.com",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"could not connect with {plugin_token}", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(store=store, http_client=http_client)

    with pytest.raises(CopilotTransportError) as error:
        await gateway.responses(user_id=user_id, model="gpt-5.4", instructions=None, input=[])

    assert plugin_token not in str(error.value)
    assert "<redacted-token>" in str(error.value)
    body = metrics_text()
    assert (
        'logan_copilot_gateway_requests_total{model="gpt-5.4",provider="github_copilot",'
        'status="failed",stream="false"}'
    ) in body
    assert plugin_token not in body
    await http_client.aclose()


@pytest.mark.asyncio
async def test_exchange_transport_errors_redact_source_token() -> None:
    store, user_id = _store_and_user()
    source_token = "gho_secret_source_token"
    store.save_credential(
        user_id=user_id,
        credential_type="github_source_oauth",
        token=source_token,
        github_base_url="https://github.com",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed with {source_token}", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(store=store, http_client=http_client)

    with pytest.raises(CopilotTransportError) as error:
        await gateway.responses(user_id=user_id, model="gpt-5.4", instructions=None, input=[])

    assert source_token not in str(error.value)
    assert "<redacted-token>" in str(error.value)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_revoked_stored_credentials_are_not_used_without_env_fallback() -> None:
    store, user_id = _store_and_user()
    store.save_credential(
        user_id=user_id,
        credential_type="github_source_oauth",
        token="gho_revoked_source_token",
        github_base_url="https://github.com",
    )
    store.revoke_credentials(user_id)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"revoked credential should not make {request.method} request")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(
        store=store,
        app_settings=Settings(github_copilot_token=None, github_source_token=None),
        http_client=http_client,
    )

    with pytest.raises(CopilotCredentialError):
        await gateway.responses(user_id=user_id, model="gpt-5.4", instructions=None, input=[])
    await http_client.aclose()
