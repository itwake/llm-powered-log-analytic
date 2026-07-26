from __future__ import annotations

import asyncio

import pytest
from app.config import Settings
from app.main import create_app
from app.store import create_ephemeral_store, sanitize_error_message
from httpx import ASGITransport, AsyncClient


def test_sanitized_text_accepts_a_length_limit() -> None:
    assert sanitize_error_message("secret=value " + "x" * 20, max_length=12) == "secret=[reda"


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
