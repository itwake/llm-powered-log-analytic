from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from app.config import Settings
from app.main import create_app
from app.services.object_store import file_uri_to_path
from app.store import create_ephemeral_store, sanitize_error_message
from httpx import ASGITransport, AsyncClient
from tests.model_gateway_stub import StubModelGateway


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
)
async def test_development_api_allows_loopback_web_origins(origin: str) -> None:
    store = create_ephemeral_store(
        Settings(
            env="development",
            cors_allowed_origins="http://localhost:3000",
        )
    )
    app = create_app(store=store)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8000",
    ) as client:
        response = await client.options(
            "/api/cases",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


def test_sanitized_text_accepts_a_length_limit() -> None:
    assert sanitize_error_message("secret=value " + "x" * 20, max_length=12) == "secret=[reda"


@pytest.mark.asyncio
async def test_case_access_is_owner_only() -> None:
    store = create_ephemeral_store(Settings())
    owner = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name=None,
    )
    other = store.register_user(
        email="other@example.com",
        username="other",
        full_name=None,
    )
    case = store.create_case(user_id=owner.id, data={"title": "Private incident"})
    token, _ = store.create_session(other.id)
    app = create_app(store=store)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"logan_session": token},
    ) as client:
        response = await client.get(f"/api/cases/{case.id}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_rejects_a_run_created_without_llm() -> None:
    store = create_ephemeral_store(Settings(llm_provider="none"))
    user = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name=None,
    )
    token, _ = store.create_session(user.id)
    case = store.create_case(user_id=user.id, data={"title": "Incident"})
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)
    app = create_app(store=store, model_gateway=StubModelGateway())

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"logan_session": token},
    ) as client:
        response = await client.post(
            "/api/chat/stream",
            json={
                "message": "What happened?",
                "case_id": case.id,
                "analysis_run_id": run.id,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "LLM was not enabled for this analysis run"


@pytest.mark.asyncio
async def test_case_upload_analysis_and_reports() -> None:
    store = create_ephemeral_store(Settings())
    user = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name="Case Owner",
        external_id="owner-1",
    )
    token, _ = store.create_session(user.id)
    app = create_app(store=store)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"logan_session": token},
    ) as client:
        created = await client.post("/api/cases", json={"title": "Checkout incident"})
        assert created.status_code == 200
        case_id = created.json()["case_id"]

        content = b"2026-01-01T00:00:00Z ERROR payment-service connection pool exhausted\n"
        upload = await client.post(
            f"/api/cases/{case_id}/uploads",
            json={
                "filename": "incident.log",
                "content_type": "text/plain",
                "size_bytes": len(content),
            },
        )
        assert upload.status_code == 200
        uploaded = await client.put(upload.json()["upload_url"], content=content)
        assert uploaded.status_code == 200

        started = await client.post(
            f"/api/cases/{case_id}/analysis-runs",
            json={"input_file_ids": [upload.json()["file_id"]]},
        )
        assert started.status_code == 200
        run_id = started.json()["analysis_run_id"]

        for _ in range(100):
            run = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}")
            if run.json()["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.01)
        assert run.json()["status"] == "completed", run.text

        summary = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/summary")
        logs = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/logs")
        assert summary.status_code == 200
        assert logs.status_code == 200
        assert logs.json()["total"] == 1
        assert run.json()["progress"]["steps"]


@pytest.mark.asyncio
async def test_upload_limit_uses_runtime_configuration(tmp_path: Path) -> None:
    store = create_ephemeral_store(
        Settings(
            local_object_store_dir=str(tmp_path),
            max_upload_bytes=8,
        )
    )
    user = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name=None,
    )
    token, _ = store.create_session(user.id)
    case = store.create_case(user_id=user.id, data={"title": "Upload limit"})
    app = create_app(store=store)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"logan_session": token},
    ) as client:
        rejected = await client.post(
            f"/api/cases/{case.id}/uploads",
            json={
                "filename": "too-large.log",
                "size_bytes": 9,
            },
        )
        assert rejected.status_code == 413
        assert rejected.json()["detail"] == (
            "upload exceeds the configured 8 bytes limit"
        )

        upload = await client.post(
            f"/api/cases/{case.id}/uploads",
            json={
                "filename": "configured.log",
                "size_bytes": 8,
            },
        )
        assert upload.status_code == 200
        upload_record = store.get_upload(upload.json()["file_id"])
        assert upload_record is not None
        target_path = file_uri_to_path(upload_record.object_uri)

        oversized_content = await client.put(
            upload.json()["upload_url"],
            content=b"123456789",
        )
        assert oversized_content.status_code == 413
        assert not target_path.exists()
        assert list(tmp_path.rglob("*.part")) == []

        completed = await client.put(
            upload.json()["upload_url"],
            content=b"12345678",
        )
        assert completed.status_code == 200
        assert completed.json()["size_bytes"] == 8
        assert target_path.read_bytes() == b"12345678"


@pytest.mark.asyncio
async def test_analysis_requires_completed_upload() -> None:
    store = create_ephemeral_store(Settings())
    user = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name=None,
    )
    token, _ = store.create_session(user.id)
    app = create_app(store=store)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"logan_session": token},
    ) as client:
        case = (await client.post("/api/cases", json={"title": "Incident"})).json()
        response = await client.post(
            f"/api/cases/{case['case_id']}/analysis-runs",
            json={"input_file_ids": []},
        )
        assert response.status_code == 422
