from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from logan_workers.activities.inference import MockCopilotAnnotationGateway

from app.config import Settings
from app.main import create_app
from app.services.copilot_auth_service import MockGitHubDeviceClient
from app.sqlalchemy_store import SQLAlchemyStore
from app.store import create_store


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")


async def _client(store: SQLAlchemyStore) -> AsyncClient:
    app = create_app(
        store=store,
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_sqlalchemy_store_persists_api_state_after_recreation(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        local_object_store_dir=str(tmp_path / "object-store"),
    )
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    client = await _client(store)

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "persistent.engineer@example.com",
            "username": "persistent-engineer",
            "full_name": "Persistent Engineer",
            "password": "password123",
        },
    )
    assert register.status_code == 200, register.text
    login = await client.post(
        "/api/auth/login",
        json={"email_or_username": "persistent-engineer", "password": "password123"},
    )
    assert login.status_code == 200, login.text

    started_auth = await client.post(
        "/api/copilot/auth/start", json={"github_base_url": "https://github.com"}
    )
    assert started_auth.status_code == 200, started_auth.text
    auth_id = started_auth.json()["auth_id"]
    assert (await client.post("/api/copilot/auth/check", json={"auth_id": auth_id})).json()[
        "status"
    ] == "pending"
    authorized = await client.post("/api/copilot/auth/check", json={"auth_id": auth_id})
    assert authorized.json()["status"] == "authorized"

    case = await client.post(
        "/api/cases",
        json={
            "title": "Checkout API intermittent 500 errors",
            "issue_description": "Customers report intermittent 500 during checkout.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "production",
            "incident_start": "2026-06-06T10:00:00Z",
            "incident_end": "2026-06-06T11:00:00Z",
            "timezone": "UTC",
        },
    )
    assert case.status_code == 200, case.text
    case_id = case.json()["case_id"]

    content = b"2026-06-06T10:00:00Z ERROR gateway request failed status=500 path=/checkout\n"
    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "gateway.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    assert upload.status_code == 200, upload.text
    file_id = upload.json()["file_id"]
    expected_sha = hashlib.sha256(content).hexdigest()
    upload_before_sha = store.get_upload(file_id)
    assert upload_before_sha is not None
    assert upload_before_sha.sha256 is None
    assert upload_before_sha.completed is False

    uploaded = await client.put(
        upload.json()["upload_url"],
        content=content,
        headers={"content-type": "text/plain"},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["sha256"] == expected_sha

    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={"sha256": expected_sha},
    )
    assert complete.status_code == 200, complete.text

    run = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={
            "input_paths": [str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            "config": {"default_window_size_seconds": 60},
        },
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["analysis_run_id"]

    logs = await client.get(
        f"/api/cases/{case_id}/analysis-runs/{run_id}/logs",
        params={"q": "timeout", "service": "payment-service"},
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["items"]

    export = await client.post(
        f"/api/cases/{case_id}/analysis-runs/{run_id}/exports",
        json={"export_type": "markdown", "include_sections": ["causal_summary"]},
    )
    assert export.status_code == 200, export.text
    export_id = export.json()["export_id"]

    graph = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-graph")
    assert graph.status_code == 200, graph.text
    feedback = await client.post(
        f"/api/cases/{case_id}/feedback",
        json={
            "analysis_run_id": run_id,
            "target_type": "causal_edge",
            "target_id": graph.json()["edges"][0]["id"],
            "feedback_type": "wrong_causal_edge",
            "rating": 1,
            "comment": "Needs validation",
        },
    )
    assert feedback.status_code == 200, feedback.text
    feedback_id = feedback.json()["feedback_id"]
    cookies = dict(client.cookies)
    await client.aclose()

    recreated_store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    recreated_client = await _client(recreated_store)
    recreated_client.cookies.update(cookies)

    me = await recreated_client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["user"]["has_copilot_credential"] is True

    listed = await recreated_client.get("/api/cases")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["case_id"] == case_id

    fetched_case = await recreated_client.get(f"/api/cases/{case_id}")
    assert fetched_case.status_code == 200, fetched_case.text
    assert fetched_case.json()["status"] == "ready"

    persisted_upload = recreated_store.get_upload(file_id)
    assert persisted_upload is not None
    assert persisted_upload.sha256 == expected_sha
    assert persisted_upload.completed is True

    status = await recreated_client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "completed"
    assert status.json()["progress"]["templates"] > 0
    run_list = await recreated_client.get(f"/api/cases/{case_id}/analysis-runs")
    assert run_list.status_code == 200, run_list.text
    assert run_list.json()["total"] == 1
    assert run_list.json()["items"][0]["analysis_run_id"] == run_id
    assert run_list.json()["items"][0]["model_provider"] == "github_copilot"

    summary = await recreated_client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["items"]

    causal_summary = await recreated_client.get(
        f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary"
    )
    assert causal_summary.status_code == 200, causal_summary.text
    assert "candidate" in causal_summary.json()["summary_markdown"].lower()

    recreated_export = recreated_store.get_export(export_id)
    assert recreated_export is not None
    assert recreated_export.object_uri.startswith("memory://")

    recreated_feedback = recreated_store.get_feedback(feedback_id)
    assert recreated_feedback is not None
    assert recreated_feedback.comment == "Needs validation"

    audit_actions = {record.action for record in recreated_store.list_audit_logs(case_id=case_id)}
    assert {
        "case.create",
        "analysis.start",
        "analysis.complete",
        "export.create",
        "feedback.submit",
        "raw_log.search",
    }.issubset(audit_actions)
    await recreated_client.aclose()


def test_create_store_auto_uses_sqlalchemy_when_database_url_is_set(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    store = create_store(Settings(database_url=database_url, store_backend="auto"))
    assert isinstance(store, SQLAlchemyStore)
