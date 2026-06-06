from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.store import InMemoryStore


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")


async def _authenticated_client() -> tuple[AsyncClient, str]:
    store = InMemoryStore()
    app = create_app(store=store)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    register = await client.post(
        "/api/auth/register",
        json={
            "email": "engineer@example.com",
            "username": "engineer",
            "full_name": "LogAn Engineer",
            "password": "password123",
        },
    )
    assert register.status_code == 200, register.text
    login = await client.post(
        "/api/auth/login",
        json={"email_or_username": "engineer", "password": "password123"},
    )
    assert login.status_code == 200
    return client, store.users_by_username["engineer"]


@pytest.mark.asyncio
async def test_auth_and_copilot_auth_api() -> None:
    client, _ = await _authenticated_client()
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["has_copilot_credential"] is False

    started = await client.post("/api/copilot/auth/start", json={"github_base_url": "https://github.com"})
    assert started.status_code == 200
    auth_id = started.json()["auth_id"]
    pending = await client.post("/api/copilot/auth/check", json={"auth_id": auth_id})
    assert pending.json()["status"] == "pending"
    authorized = await client.post("/api/copilot/auth/check", json={"auth_id": auth_id})
    assert authorized.json()["status"] == "authorized"
    assert "token" not in authorized.text.lower().replace("token_type", "")

    me_after = await client.get("/api/auth/me")
    assert me_after.json()["user"]["has_copilot_credential"] is True
    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401
    await client.aclose()


@pytest.mark.asyncio
async def test_case_analysis_report_and_feedback_apis() -> None:
    client, _ = await _authenticated_client()
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
    assert case.status_code == 200
    case_id = case.json()["case_id"]

    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "logs.zip", "content_type": "application/zip", "size_bytes": 123},
    )
    assert upload.status_code == 200
    file_id = upload.json()["file_id"]
    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={"sha256": "abc123"},
    )
    assert complete.status_code == 200

    run = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={
            "input_paths": [str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            "config": {"default_window_size_seconds": 60},
        },
    )
    assert run.status_code == 200
    run_id = run.json()["analysis_run_id"]
    status = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}")
    assert status.json()["status"] == "completed"
    assert status.json()["progress"]["templates"] > 0

    summary = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/summary")
    body = summary.json()
    assert body["items"]
    assert all(item["golden_signal"] != "information" for item in body["items"])
    assert body["reduction"]["estimated_review_reduction"] > 0

    temporal = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/temporal")
    assert any(series["name"] == "availability" for series in temporal.json()["series"])

    logs = await client.get(
        f"/api/cases/{case_id}/analysis-runs/{run_id}/logs",
        params={"q": "timeout", "service": "payment-service"},
    )
    assert logs.json()["items"]
    assert all("timeout" in item["message"].lower() for item in logs.json()["items"])

    graph = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-graph")
    graph_body = graph.json()
    assert graph_body["edges"]
    assert all(edge["edge_type"] == "candidate_cause" for edge in graph_body["edges"])
    assert all(edge["needs_validation"] for edge in graph_body["edges"])

    causal_summary = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary")
    assert "candidate" in causal_summary.json()["summary_markdown"].lower()
    assert causal_summary.json()["evidence_refs"]

    for export_type in ("markdown", "html", "json"):
        export = await client.post(
            f"/api/cases/{case_id}/analysis-runs/{run_id}/exports",
            json={"export_type": export_type, "include_sections": ["causal_summary"]},
        )
        assert export.status_code == 200
        assert export.json()["download_url"].startswith("memory://")

    feedback = await client.post(
        f"/api/cases/{case_id}/feedback",
        json={
            "analysis_run_id": run_id,
            "target_type": "causal_edge",
            "target_id": graph_body["edges"][0]["id"],
            "feedback_type": "wrong_causal_edge",
            "rating": 1,
            "comment": "Needs validation",
        },
    )
    assert feedback.status_code == 200
    assert feedback.json()["feedback_id"]

    chat = await client.post(
        "/api/chat",
        json={
            "message": "Why is auth-service ranked?",
            "case_id": case_id,
            "analysis_run_id": run_id,
        },
    )
    assert "candidate" in chat.json()["message"].lower()
    tasks = await client.post("/api/tasks/execute", json={"task_name": "noop", "arguments": {}})
    assert tasks.json()["runtime_type"] == "github_copilot"
    await client.aclose()
