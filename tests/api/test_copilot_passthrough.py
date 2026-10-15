from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.copilot_passthrough import (
    MAX_REQUEST_BODY_BYTES,
    CopilotPassThrough,
    copilot_api_base_url,
)
from app.main import create_app
from app.store import create_ephemeral_store

GITHUB_TOKEN = "gho_caller_token_1234567890"
COPILOT_TOKEN = "tid=abc;exp=1999999999;proxy-ep=proxy.individual.githubcopilot.com;sku=x"
TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
RESPONSES_URL = "https://api.individual.githubcopilot.com/responses"
AUTH_GITHUB = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
AUTH_COPILOT = {"Authorization": f"Bearer {COPILOT_TOKEN}"}
REQUEST_BODY = b'{"model": "gpt-5.4",  "input": "hi", "stream": false}'

Handler = Callable[[httpx.Request], Any]


def _app(handler: Handler, *, enabled: bool = True) -> FastAPI:
    settings = Settings(copilot_passthrough_enabled=enabled)
    app = create_app(store=create_ephemeral_store(settings))
    app.state.copilot_passthrough = CopilotPassThrough(
        app_settings=settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no upstream request expected, got {request.url}")


class _ChunkStream(httpx.AsyncByteStream):
    """An upstream body that arrives in several pieces, like server-sent events."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_pass_through_is_off_unless_enabled() -> None:
    assert Settings().copilot_passthrough_enabled is False
    app = _app(_unexpected, enabled=False)

    async with _client(app) as client:
        token = await client.post("/api/copilot/token", headers=AUTH_GITHUB)
        responses = await client.post(
            "/api/copilot/responses",
            headers=AUTH_COPILOT,
            content=REQUEST_BODY,
        )

    assert token.status_code == 503
    assert responses.status_code == 503
    assert "LOGAN_COPILOT_PASSTHROUGH_ENABLED" in token.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/copilot/token", "/api/copilot/responses"])
@pytest.mark.parametrize("authorization", [None, "Basic abc", "Bearer ", "gho_no_scheme"])
async def test_both_relays_require_a_bearer_token(path: str, authorization: str | None) -> None:
    app = _app(_unexpected)
    headers = {"Authorization": authorization} if authorization is not None else {}

    async with _client(app) as client:
        response = await client.post(path, headers=headers, content=REQUEST_BODY)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_token_exchange_relays_the_github_answer_verbatim() -> None:
    github_reply = (
        b'{"token": "' + COPILOT_TOKEN.encode() + b'", "expires_at": 1999999999, '
        b'"refresh_in": 1500, "endpoints": {"api": "https://api.individual.githubcopilot.com"}}'
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == TOKEN_URL
        assert request.headers["authorization"] == f"Bearer {GITHUB_TOKEN}"
        assert request.headers["accept"] == "application/json"
        assert request.headers["editor-version"] == "vscode/1.133.0"
        assert request.headers["copilot-integration-id"] == "vscode-chat"
        assert request.headers["user-agent"].startswith("GitHubCopilotChat/")
        return httpx.Response(
            200,
            content=github_reply,
            headers={"content-type": "application/json; charset=utf-8", "x-request-id": "gh-1"},
        )

    app = _app(handler)
    async with _client(app) as client:
        response = await client.post("/api/copilot/token", headers=AUTH_GITHUB)

    assert response.status_code == 200
    assert response.content == github_reply
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["x-request-id"] == "gh-1"
    await app.state.copilot_passthrough.aclose()


@pytest.mark.asyncio
async def test_token_exchange_relays_a_github_rejection_with_its_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    app = _app(handler)
    async with _client(app) as client:
        response = await client.post("/api/copilot/token", headers=AUTH_GITHUB)

    assert response.status_code == 401
    assert response.json() == {"message": "Bad credentials"}
    assert "www-authenticate" not in response.headers


@pytest.mark.asyncio
async def test_responses_are_forwarded_unchanged_with_the_copilot_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == RESPONSES_URL
        assert request.content == REQUEST_BODY
        assert request.headers["authorization"] == f"Bearer {COPILOT_TOKEN}"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["accept"] == "application/vnd.github.copilot-chat-preview+json"
        assert request.headers["openai-intent"] == "conversation-edits"
        assert request.headers["x-initiator"] == "user"
        assert request.headers["editor-version"] == "vscode/1.133.0"
        assert request.headers["editor-plugin-version"] == "copilot-chat/0.41.0"
        assert request.headers["copilot-integration-id"] == "vscode-chat"
        assert request.headers["user-agent"] == "GitHubCopilotChat/0.41.0"
        # The endpoint answers "invalid apiVersion" when this REST API header is sent.
        assert "x-github-api-version" not in request.headers
        # Nothing of the caller's own transport leaks upstream.
        assert "cookie" not in request.headers
        assert "x-forwarded-for" not in request.headers
        return httpx.Response(
            200,
            json={"id": "resp_1", "output": []},
            headers={"x-request-id": "cp-1"},
        )

    app = _app(handler)
    async with _client(app) as client:
        response = await client.post(
            "/api/copilot/responses",
            content=REQUEST_BODY,
            headers={
                **AUTH_COPILOT,
                "Content-Type": "application/json",
                "User-Agent": "my-tool/1.0",
                "Cookie": "logan_session=abc",
                "X-Forwarded-For": "10.1.2.3",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"id": "resp_1", "output": []}
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-request-id"] == "cp-1"
    assert "content-length" not in response.headers


@pytest.mark.asyncio
async def test_callers_may_set_the_intent_headers_but_not_the_accept_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "application/vnd.github.copilot-chat-preview+json"
        assert request.headers["openai-intent"] == "conversation-panel"
        assert request.headers["x-initiator"] == "agent"
        assert request.headers["x-request-id"] == "caller-7"
        assert request.headers["authorization"] == f"Bearer {COPILOT_TOKEN}"
        return httpx.Response(200, json={"id": "resp_2"})

    app = _app(handler)
    async with _client(app) as client:
        response = await client.post(
            "/api/copilot/responses",
            content=REQUEST_BODY,
            headers={
                **AUTH_COPILOT,
                "Accept": "text/event-stream",
                "Openai-Intent": "conversation-panel",
                "X-Initiator": "agent",
                "X-Request-Id": "caller-7",
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_streamed_responses_are_relayed_chunk_by_chunk() -> None:
    chunks = [
        b"event: response.created\ndata: {}\n\n",
        b"event: response.output_text.delta\ndata: {\"delta\": \"Gateway\"}\n\n",
        b"event: response.completed\ndata: {}\n\n",
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_ChunkStream(chunks),
        )

    app = _app(handler)
    status, headers, bodies = await _asgi_post(
        app,
        "/api/copilot/responses",
        headers={**AUTH_COPILOT, "Content-Type": "application/json"},
        body=b'{"model": "gpt-5.4", "input": "hi", "stream": true}',
    )

    assert status == 200
    assert headers["content-type"] == "text/event-stream"
    assert "content-length" not in headers
    assert [body for body in bodies if body] == chunks


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (COPILOT_TOKEN, "https://api.individual.githubcopilot.com"),
        (
            "tid=abc;proxy-ep=proxy.business.githubcopilot.com:443",
            "https://api.business.githubcopilot.com",
        ),
        ("tid=abc;proxy-ep=api.enterprise.githubcopilot.com", "https://api.enterprise.githubcopilot.com"),
        ("tid=abc;exp=1", "https://api.githubcopilot.com"),
        ("tid=abc;proxy-ep=evil.example.test", "https://api.githubcopilot.com"),
        ("tid=abc;proxy-ep=proxy.githubcopilot.com.evil.example.test", "https://api.githubcopilot.com"),
        ("tid=abc;proxy-ep=10.0.0.5:8080", "https://api.githubcopilot.com"),
        ("tid=abc;proxy-ep=http://user@evil.example.test/", "https://api.githubcopilot.com"),
    ],
)
def test_relay_targets_follow_a_token_only_to_copilot_hosts(token: str, expected: str) -> None:
    assert copilot_api_base_url(token) == expected


@pytest.mark.asyncio
async def test_a_crafted_token_cannot_turn_the_relay_towards_another_host() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.githubcopilot.com/responses"
        return httpx.Response(200, json={"id": "resp_3"})

    app = _app(handler)
    async with _client(app) as client:
        response = await client.post(
            "/api/copilot/responses",
            content=REQUEST_BODY,
            headers={"Authorization": "Bearer tid=abc;proxy-ep=internal-host.corp.example:8080"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"not json", b"[]", b'"text"', b"null"])
async def test_responses_reject_bodies_that_are_not_json_objects(content: bytes) -> None:
    app = _app(_unexpected)

    async with _client(app) as client:
        response = await client.post(
            "/api/copilot/responses",
            content=content,
            headers={**AUTH_COPILOT, "Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "request body must be a JSON object"


@pytest.mark.asyncio
async def test_responses_reject_oversized_bodies_before_relaying_them() -> None:
    app = _app(_unexpected)
    oversized = b'{"input": "' + b"x" * MAX_REQUEST_BODY_BYTES + b'"}'

    async with _client(app) as client:
        streamed = await client.post(
            "/api/copilot/responses",
            content=oversized,
            headers=AUTH_COPILOT,
        )
        declared = await client.post(
            "/api/copilot/responses",
            content=REQUEST_BODY,
            headers={**AUTH_COPILOT, "Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)},
        )

    assert streamed.status_code == 413
    assert declared.status_code == 413


@pytest.mark.asyncio
async def test_upstream_errors_are_relayed_and_transport_failures_are_502() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/copilot_internal/v2/token":
            raise httpx.ConnectError(f"proxy refused {GITHUB_TOKEN}")
        if b"unknown_field" in request.content:
            return httpx.Response(400, json={"error": {"message": "unknown field"}})
        raise httpx.ReadTimeout(f"timed out holding {COPILOT_TOKEN}")

    app = _app(handler)
    async with _client(app) as client:
        token = await client.post("/api/copilot/token", headers=AUTH_GITHUB)
        rejected = await client.post(
            "/api/copilot/responses",
            content=b'{"model": "gpt-5.4", "unknown_field": 1}',
            headers=AUTH_COPILOT,
        )
        timed_out = await client.post(
            "/api/copilot/responses",
            content=REQUEST_BODY,
            headers=AUTH_COPILOT,
        )

    assert token.status_code == 502
    assert "GitHub Copilot token exchange transport failed" in token.json()["detail"]
    assert GITHUB_TOKEN not in token.text
    assert rejected.status_code == 400
    assert rejected.json() == {"error": {"message": "unknown field"}}
    assert timed_out.status_code == 502
    assert "GitHub Copilot responses transport failed" in timed_out.json()["detail"]
    assert COPILOT_TOKEN not in timed_out.text


async def _asgi_post(
    app: FastAPI,
    path: str,
    *,
    headers: dict[str, str],
    body: bytes,
) -> tuple[int, dict[str, str], list[bytes]]:
    """Call the app as an ASGI server would and return the body frames it sent, one per
    ``http.response.body`` message, which is what an HTTP client sees as separate chunks."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    delivered = False
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()  # the connection stays open until the response is done
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    start = messages[0]
    assert start["type"] == "http.response.start"
    response_headers = {name.decode(): value.decode() for name, value in start["headers"]}
    bodies = [message["body"] for message in messages[1:] if message["type"] == "http.response.body"]
    return start["status"], response_headers, bodies
