from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import tables
from app.services.github_copilot_auth import GitHubDeviceFlow
from app.store import Store, UserRecord, create_ephemeral_store
from tests.model_gateway_stub import StubModelGateway

AI_PLATFORM_PAYLOAD: dict[str, Any] = {
    "name": "Corporate AI Platform",
    "provider_type": "ai_platform",
    "default_model": "gpt-5.6-terra",
    "default_reasoning_effort": "medium",
    "config": {
        "chat_host": "https://ai.example.test/",
        "chat_uri": "/v1/chat",
        "usercase": "logan",
    },
    "secrets": {"token": "trust-token-value"},
}


def _user(store: Store, name: str = "owner") -> tuple[UserRecord, str]:
    user = store.register_user(
        email=f"{name}@example.com",
        username=name,
        full_name=None,
    )
    token, _ = store.create_session(user.id)
    return user, token


def _client(app, token: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"logan_session": token},
    )


@pytest.mark.asyncio
async def test_catalog_lists_provider_types_models_and_thinking_levels() -> None:
    store = create_ephemeral_store(
        Settings(ai_platform_chat_host="https://ai.example.test")
    )
    _, token = _user(store)
    app = create_app(store=store)

    async with _client(app, token) as client:
        response = await client.get("/api/llm-providers/catalog")

    assert response.status_code == 200
    catalog = response.json()
    assert [item["provider_type"] for item in catalog["provider_types"]] == [
        "ai_platform",
        "github_copilot",
    ]
    copilot = catalog["provider_types"][1]
    assert copilot["supports_device_flow"] is True
    assert "gpt-5.6-terra" in copilot["models"]
    assert [item["value"] for item in catalog["reasoning_efforts"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert catalog["default_reasoning_effort"] == "high"
    assert catalog["ai_platform_defaults"]["chat_host"] == "https://ai.example.test"


@pytest.mark.asyncio
async def test_create_ai_platform_provider_encrypts_secrets_and_masks_them() -> None:
    store = create_ephemeral_store(Settings(secret_key="unit-test-secret-key"))
    user, token = _user(store)
    app = create_app(store=store)

    async with _client(app, token) as client:
        created = await client.post("/api/llm-providers", json=AI_PLATFORM_PAYLOAD)
        assert created.status_code == 200, created.text
        listed = await client.get("/api/llm-providers")

    body = created.json()
    assert body["provider_type"] == "ai_platform"
    assert body["provider_label"] == "AI Platform"
    assert body["is_default"] is True
    assert body["credentials_configured"] is True
    assert body["credential_summary"] == "Trust token configured"
    assert body["secret_fields"] == ["token"]
    assert body["default_model"] == "gpt-5.6-terra"
    assert body["default_reasoning_effort"] == "medium"
    assert body["config"]["chat_host"] == "https://ai.example.test"
    assert "trust-token-value" not in created.text
    assert "trust-token-value" not in listed.text
    assert listed.json()["total"] == 1

    provider = store.get_llm_provider(body["provider_id"])
    assert provider is not None
    assert provider.secrets == {"token": "trust-token-value"}
    assert "trust-token-value" not in repr(provider)
    with store.session_factory() as session:
        row = session.get(tables.LlmProvider, body["provider_id"])
        assert row.encrypted_secrets.startswith("enc:v1:")
        assert "trust-token-value" not in row.encrypted_secrets


@pytest.mark.asyncio
async def test_provider_validation_rejects_bad_definitions() -> None:
    store = create_ephemeral_store(Settings())
    _, token = _user(store)
    app = create_app(store=store)

    async with _client(app, token) as client:
        unknown_type = await client.post(
            "/api/llm-providers",
            json={"name": "x", "provider_type": "openai"},
        )
        missing_host = await client.post(
            "/api/llm-providers",
            json={"name": "x", "provider_type": "ai_platform"},
        )
        bad_default = await client.post(
            "/api/llm-providers",
            json={
                "name": "x",
                "provider_type": "github_copilot",
                "models": ["gpt-5.4"],
                "default_model": "gpt-5.5",
            },
        )
        bad_effort = await client.post(
            "/api/llm-providers",
            json={
                "name": "x",
                "provider_type": "github_copilot",
                "default_reasoning_effort": "ultra",
            },
        )
        partial_ib2b = await client.post(
            "/api/llm-providers",
            json={
                "name": "x",
                "provider_type": "ai_platform",
                "config": {"chat_host": "https://ai.example.test", "username": "alice"},
            },
        )
        unknown_field = await client.post(
            "/api/llm-providers",
            json={
                "name": "x",
                "provider_type": "github_copilot",
                "config": {"api_key": "nope"},
            },
        )
        bad_url = await client.post(
            "/api/llm-providers",
            json={
                "name": "x",
                "provider_type": "ai_platform",
                "config": {"chat_host": "ai.example.test"},
            },
        )
        first = await client.post(
            "/api/llm-providers",
            json={"name": "Copilot", "provider_type": "github_copilot"},
        )
        duplicate = await client.post(
            "/api/llm-providers",
            json={"name": "Copilot", "provider_type": "github_copilot"},
        )

    assert unknown_type.status_code == 400
    assert "provider_type" in unknown_type.json()["detail"]
    assert missing_host.status_code == 400
    assert "chat_host" in missing_host.json()["detail"]
    assert bad_default.status_code == 400
    assert bad_effort.status_code == 400
    assert partial_ib2b.status_code == 400
    assert "usercase" in partial_ib2b.json()["detail"]
    assert unknown_field.status_code == 400
    assert bad_url.status_code == 400
    assert first.status_code == 200
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_default_provider_switches_and_survives_deletion() -> None:
    store = create_ephemeral_store(Settings())
    _, token = _user(store)
    app = create_app(store=store)

    async with _client(app, token) as client:
        first = (await client.post("/api/llm-providers", json=AI_PLATFORM_PAYLOAD)).json()
        second = (
            await client.post(
                "/api/llm-providers",
                json={"name": "Copilot", "provider_type": "github_copilot"},
            )
        ).json()
        assert first["is_default"] is True
        assert second["is_default"] is False
        assert second["credentials_configured"] is False

        promoted = await client.patch(
            f"/api/llm-providers/{second['provider_id']}",
            json={"is_default": True, "name": "Copilot (work)"},
        )
        assert promoted.status_code == 200
        assert promoted.json()["is_default"] is True
        assert promoted.json()["name"] == "Copilot (work)"
        demoted = await client.get(f"/api/llm-providers/{first['provider_id']}")
        assert demoted.json()["is_default"] is False

        deleted = await client.delete(f"/api/llm-providers/{second['provider_id']}")
        assert deleted.status_code == 200
        remaining = await client.get("/api/llm-providers")

    items = remaining.json()["items"]
    assert [item["provider_id"] for item in items] == [first["provider_id"]]
    assert items[0]["is_default"] is True


@pytest.mark.asyncio
async def test_provider_update_merges_secrets_and_models() -> None:
    store = create_ephemeral_store(Settings())
    _, token = _user(store)
    app = create_app(store=store)

    async with _client(app, token) as client:
        created = (await client.post("/api/llm-providers", json=AI_PLATFORM_PAYLOAD)).json()
        provider_id = created["provider_id"]
        switched = await client.patch(
            f"/api/llm-providers/{provider_id}",
            json={
                "config": {
                    "username": "alice",
                    "usercase": "logan",
                    "ib2b_host": "https://identity.example.test",
                    "ib2b_uri": "/token",
                },
                "secrets": {"password": "s3cret", "token": ""},
                "models": ["gpt-5.4", "custom-model-1"],
                "default_model": "custom-model-1",
            },
        )
        assert switched.status_code == 200, switched.text
        invalid_model = await client.patch(
            f"/api/llm-providers/{provider_id}",
            json={"models": ["bad model id!"]},
        )
        type_change = await client.patch(
            f"/api/llm-providers/{provider_id}",
            json={"models": ["gpt-5.4"], "default_model": "gpt-5.4"},
        )

    body = switched.json()
    assert body["secret_fields"] == ["password"]
    assert body["credential_summary"] == "iB2B credentials for alice"
    assert body["models"] == ["gpt-5.4", "custom-model-1"]
    assert body["default_model"] == "custom-model-1"
    assert "s3cret" not in switched.text
    assert invalid_model.status_code == 400
    assert type_change.status_code == 200
    assert type_change.json()["default_model"] == "gpt-5.4"
    provider = store.get_llm_provider(provider_id)
    assert provider is not None
    assert provider.secrets == {"password": "s3cret"}
    assert provider.config["chat_host"] == "https://ai.example.test"


@pytest.mark.asyncio
async def test_providers_are_scoped_to_their_owner() -> None:
    store = create_ephemeral_store(Settings())
    _, owner_token = _user(store, "owner")
    _, other_token = _user(store, "other")
    app = create_app(store=store)

    async with _client(app, owner_token) as owner:
        created = (await owner.post("/api/llm-providers", json=AI_PLATFORM_PAYLOAD)).json()
    async with _client(app, other_token) as other:
        listed = await other.get("/api/llm-providers")
        fetched = await other.get(f"/api/llm-providers/{created['provider_id']}")
        patched = await other.patch(
            f"/api/llm-providers/{created['provider_id']}",
            json={"name": "stolen"},
        )
        deleted = await other.delete(f"/api/llm-providers/{created['provider_id']}")
        tested = await other.post(f"/api/llm-providers/{created['provider_id']}/test")

    assert listed.json()["total"] == 0
    assert fetched.status_code == 404
    assert patched.status_code == 404
    assert deleted.status_code == 404
    assert tested.status_code == 404
    assert store.get_llm_provider(created["provider_id"]) is not None


@pytest.mark.asyncio
async def test_analysis_run_and_chat_use_the_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = create_ephemeral_store(Settings())
    _, token = _user(store)
    gateway = StubModelGateway()
    app = create_app(store=store, model_gateway=gateway)

    async with _client(app, token) as client:
        provider = (await client.post("/api/llm-providers", json=AI_PLATFORM_PAYLOAD)).json()
        case_id = (await client.post("/api/cases", json={"title": "Checkout incident"})).json()[
            "case_id"
        ]
        content = b"2026-01-01T00:00:00Z ERROR payment-service connection pool exhausted\n"
        upload = (
            await client.post(
                f"/api/cases/{case_id}/uploads",
                json={"filename": "incident.log", "size_bytes": len(content)},
            )
        ).json()
        assert (await client.put(upload["upload_url"], content=content)).status_code == 200

        unknown_provider = await client.post(
            f"/api/cases/{case_id}/analysis-runs",
            json={"input_file_ids": [upload["file_id"]], "provider_id": "missing"},
        )
        assert unknown_provider.status_code == 404
        wrong_model = await client.post(
            f"/api/cases/{case_id}/analysis-runs",
            json={
                "input_file_ids": [upload["file_id"]],
                "provider_id": provider["provider_id"],
                "model": "not-enabled",
            },
        )
        assert wrong_model.status_code == 400

        started = await client.post(
            f"/api/cases/{case_id}/analysis-runs",
            json={
                "input_file_ids": [upload["file_id"]],
                "provider_id": provider["provider_id"],
                "model": "gpt-5.4",
                "reasoning_effort": "xhigh",
            },
        )
        assert started.status_code == 200, started.text
        run = started.json()
        assert run["model_provider"] == "ai_platform"
        assert run["model_name"] == "gpt-5.4"
        assert run["llm_provider_id"] == provider["provider_id"]
        assert run["llm_provider_name"] == "Corporate AI Platform"
        assert run["reasoning_effort"] == "xhigh"

        for _ in range(200):
            current = (
                await client.get(f"/api/cases/{case_id}/analysis-runs/{run['analysis_run_id']}")
            ).json()
            if current["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.01)
        assert current["status"] == "completed", current

        annotation_calls = [
            call for call in gateway.calls if call["metadata"]["purpose"] == "template_annotation"
        ]
        assert annotation_calls
        assert {call["model"] for call in annotation_calls} == {"gpt-5.4"}
        assert {call["reasoning_effort"] for call in annotation_calls} == {"xhigh"}
        summary_calls = [
            call for call in gateway.calls if call["metadata"]["purpose"] == "causal_summary"
        ]
        assert summary_calls and summary_calls[0]["reasoning_effort"] == "xhigh"

        chat = await client.post(
            "/api/chat/stream",
            json={
                "message": "What happened?",
                "case_id": case_id,
                "analysis_run_id": run["analysis_run_id"],
                "model": "gpt-5.6-terra",
                "reasoning_effort": "low",
            },
        )
        assert chat.status_code == 200, chat.text
        frames = [frame for frame in chat.text.split("\n\n") if frame.strip()]
        events = {
            frame.split("\n", 1)[0].removeprefix("event: "): json.loads(
                frame.split("\n", 1)[1].removeprefix("data: ")
            )
            for frame in frames
        }
        assert events["meta"] == {
            "provider_id": provider["provider_id"],
            "provider_name": "Corporate AI Platform",
            "provider_type": "ai_platform",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "low",
        }
        assert events["done"]["message"] == "Test response."
        chat_call = gateway.calls[-1]
        assert chat_call["model"] == "gpt-5.6-terra"
        assert chat_call["reasoning_effort"] == "low"

        rejected_model = await client.post(
            "/api/chat/stream",
            json={
                "message": "What happened?",
                "case_id": case_id,
                "analysis_run_id": run["analysis_run_id"],
                "model": "not-enabled",
            },
        )
        assert rejected_model.status_code == 400

        tested = await client.post(f"/api/llm-providers/{provider['provider_id']}/test")
        assert tested.status_code == 200
        assert tested.json()["ok"] is True
        assert tested.json()["model"] == "gpt-5.6-terra"


@pytest.mark.asyncio
async def test_chat_falls_back_to_run_provider_then_default_provider() -> None:
    store = create_ephemeral_store(Settings())
    user, token = _user(store)
    gateway = StubModelGateway()
    app = create_app(store=store, model_gateway=gateway)

    async with _client(app, token) as client:
        case_id = (await client.post("/api/cases", json={"title": "Incident"})).json()["case_id"]
        content = b"2026-01-01T00:00:00Z ERROR payment-service pool exhausted\n"
        upload = (
            await client.post(
                f"/api/cases/{case_id}/uploads",
                json={"filename": "incident.log", "size_bytes": len(content)},
            )
        ).json()
        await client.put(upload["upload_url"], content=content)
        run = (
            await client.post(
                f"/api/cases/{case_id}/analysis-runs",
                json={"input_file_ids": [upload["file_id"]]},
            )
        ).json()
        assert run["model_provider"] == "none"
        assert run["llm_provider_id"] is None
        for _ in range(200):
            current = (
                await client.get(f"/api/cases/{case_id}/analysis-runs/{run['analysis_run_id']}")
            ).json()
            if current["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.01)
        assert current["status"] == "completed"

        chat_payload = {
            "message": "What happened?",
            "case_id": case_id,
            "analysis_run_id": run["analysis_run_id"],
        }
        without_provider = await client.post("/api/chat/stream", json=chat_payload)
        assert without_provider.status_code == 409
        assert "No AI provider is configured" in without_provider.json()["detail"]

        unconnected = (
            await client.post(
                "/api/llm-providers",
                json={"name": "Copilot", "provider_type": "github_copilot"},
            )
        ).json()
        not_ready = await client.post("/api/chat/stream", json=chat_payload)
        assert not_ready.status_code == 409
        assert "no usable credentials" in not_ready.json()["detail"]

        await client.patch(
            f"/api/llm-providers/{unconnected['provider_id']}",
            json={"secrets": {"github_token": "gho_manual_token"}},
        )
        ready = await client.post("/api/chat/stream", json=chat_payload)
        assert ready.status_code == 200
        assert '"provider_type":"github_copilot"' in ready.text
        assert gateway.calls[-1]["model"] == "gpt-5.6-terra"
        assert gateway.calls[-1]["reasoning_effort"] == "high"
    assert gateway.calls[-1]["user_id"] == user.id


@pytest.mark.asyncio
async def test_github_device_flow_connects_a_copilot_provider() -> None:
    store = create_ephemeral_store(Settings())
    _, token = _user(store)
    app = create_app(store=store)
    polls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.url.path == "/login/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-secret",
                    "user_code": "WXYZ-9876",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 600,
                    "interval": 1,
                },
            )
        if request.url.path == "/login/oauth/access_token":
            polls += 1
            if polls == 1:
                return httpx.Response(200, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "gho_device_token"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "octocat"})
        raise AssertionError(str(request.url))

    app.state.github_device_flow = GitHubDeviceFlow(
        app_settings=store.settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async with _client(app, token) as client:
        ai_platform = (await client.post("/api/llm-providers", json=AI_PLATFORM_PAYLOAD)).json()
        wrong_type = await client.post(
            f"/api/llm-providers/{ai_platform['provider_id']}/github-device/start"
        )
        assert wrong_type.status_code == 400

        copilot = (
            await client.post(
                "/api/llm-providers",
                json={"name": "Copilot", "provider_type": "github_copilot"},
            )
        ).json()
        started = await client.post(
            f"/api/llm-providers/{copilot['provider_id']}/github-device/start"
        )
        assert started.status_code == 200, started.text
        flow = started.json()
        assert flow["user_code"] == "WXYZ-9876"
        assert flow["verification_uri"] == "https://github.com/login/device"
        assert "device-secret" not in started.text

        pending = await client.post(
            f"/api/llm-providers/{copilot['provider_id']}/github-device/check",
            json={"auth_id": flow["auth_id"]},
        )
        assert pending.json()["status"] == "pending"
        app.state.github_device_flow.pending_for(
            user_id=store.get_llm_provider(copilot["provider_id"]).user_id,
            auth_id=flow["auth_id"],
        ).last_polled_at = None
        authorized = await client.post(
            f"/api/llm-providers/{copilot['provider_id']}/github-device/check",
            json={"auth_id": flow["auth_id"]},
        )

    assert authorized.status_code == 200, authorized.text
    body = authorized.json()
    assert body["status"] == "authorized"
    assert body["github_login"] == "octocat"
    assert body["provider"]["credentials_configured"] is True
    assert body["provider"]["credential_summary"] == "GitHub account octocat"
    assert body["provider"]["secret_fields"] == ["github_token"]
    assert "gho_device_token" not in authorized.text
    provider = store.get_llm_provider(copilot["provider_id"])
    assert provider is not None
    assert provider.secrets == {"github_token": "gho_device_token"}
    assert provider.config["github_login"] == "octocat"
