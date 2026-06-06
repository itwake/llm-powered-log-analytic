from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from logan_workers.activities.inference import MockCopilotAnnotationGateway

from app.config import Settings
from app.main import create_app
from app.services.copilot_auth_service import DeviceCodePollResult, MockGitHubDeviceClient
from app.store import InMemoryStore


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")
PIPELINE_STEPS = [
    "ingest_paths",
    "merge_entries",
    "preprocess_redact",
    "drain_templating",
    "representative_sampling",
    "copilot_annotation",
    "broadcast_annotations",
    "temporal_aggregation",
    "causal_graph",
    "causal_summary",
    "export_artifacts",
]


class FailingAnnotationGateway(MockCopilotAnnotationGateway):
    async def responses(self, **kwargs):
        raise RuntimeError(
            "annotation failed source_token=gho_secret_token_1234567890 "
            "password=hunter2"
        )


async def _authenticated_client(
    app_settings: Settings | None = None,
) -> tuple[AsyncClient, InMemoryStore, str]:
    store = InMemoryStore(app_settings or Settings())
    app = create_app(
        store=store,
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
    )
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
    return client, store, store.users_by_username["engineer"]


async def _create_case(client: AsyncClient) -> str:
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
    return str(case.json()["case_id"])


async def _upload_content(
    client: AsyncClient,
    *,
    case_id: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> dict[str, object]:
    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": filename, "content_type": content_type, "size_bytes": len(content)},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["upload_url"].startswith("http://testserver/api/cases/")
    put = await client.put(
        upload.json()["upload_url"],
        content=content,
        headers={"content-type": content_type},
    )
    assert put.status_code == 200, put.text
    return put.json()


@pytest.mark.asyncio
async def test_auth_and_copilot_auth_api() -> None:
    client, _, _ = await _authenticated_client()
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
async def test_copilot_auth_api_responses_never_include_token_material() -> None:
    source_token = "gho_api_response_secret_token"
    store = InMemoryStore()
    app = create_app(
        store=store,
        copilot_auth_client=MockGitHubDeviceClient(
            [DeviceCodePollResult(status="authorized", message="authorized", access_token=source_token)]
        ),
        model_gateway=MockCopilotAnnotationGateway(),
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    await client.post(
        "/api/auth/register",
        json={
            "email": "no-token@example.com",
            "username": "no-token",
            "full_name": "No Token",
            "password": "password123",
        },
    )
    await client.post(
        "/api/auth/login",
        json={"email_or_username": "no-token", "password": "password123"},
    )

    started = await client.post("/api/copilot/auth/start", json={"github_base_url": "https://github.com"})
    checked = await client.post("/api/copilot/auth/check", json={"auth_id": started.json()["auth_id"]})
    me = await client.get("/api/auth/me")

    assert checked.json()["status"] == "authorized"
    for response in (started, checked, me):
        assert source_token not in response.text
        assert "encrypted_token" not in response.text
    await client.aclose()


@pytest.mark.asyncio
async def test_case_analysis_report_and_feedback_apis(tmp_path: Path) -> None:
    client, _, _ = await _authenticated_client(
        Settings(local_object_store_dir=str(tmp_path / "object-store"))
    )
    case_id = await _create_case(client)

    content = b"2026-06-06T10:00:00Z ERROR gateway request failed status=500 path=/checkout\n"
    uploaded = await _upload_content(
        client,
        case_id=case_id,
        filename="gateway.log",
        content_type="text/plain",
        content=content,
    )
    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{uploaded['file_id']}/complete",
        json={"sha256": uploaded["sha256"]},
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
    events = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/events")
    assert events.status_code == 200, events.text
    events_body = events.json()
    assert events_body["total"] >= len(PIPELINE_STEPS) * 2
    event_items = events_body["items"]
    assert [item["created_at"] for item in event_items] == sorted(
        item["created_at"] for item in event_items
    )
    assert {item["case_id"] for item in event_items} == {case_id}
    assert {item["analysis_run_id"] for item in event_items} == {run_id}
    completed_steps = [
        item["step_name"] for item in event_items if item["event_type"] == "completed"
    ]
    assert completed_steps == PIPELINE_STEPS
    event_metadata = json.dumps([item["metadata"] for item in event_items], sort_keys=True)
    assert "model_inputs" not in event_metadata
    assert "representative_lines" not in event_metadata
    assert "timeout calling auth-service" not in event_metadata
    run_list = await client.get(f"/api/cases/{case_id}/analysis-runs")
    assert run_list.status_code == 200
    assert run_list.json()["total"] == 1
    listed_run = run_list.json()["items"][0]
    assert listed_run["analysis_run_id"] == run_id
    assert listed_run["run_number"] == 1
    assert listed_run["status"] == "completed"
    assert listed_run["current_step"] == "completed"
    assert listed_run["progress"]["templates"] > 0
    assert listed_run["started_at"]
    assert listed_run["completed_at"]
    assert listed_run["error_message"] is None
    assert listed_run["model_provider"] == "github_copilot"
    assert listed_run["model_name"]

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


@pytest.mark.asyncio
async def test_raw_byte_upload_complete_idempotent_and_analysis_by_input_file_ids(
    tmp_path: Path,
) -> None:
    client, store, _ = await _authenticated_client(
        Settings(local_object_store_dir=str(tmp_path / "object-store"))
    )
    case_id = await _create_case(client)
    content = (
        b"2026-06-06T10:00:00Z ERROR payment-service timeout calling auth-service "
        b"duration_ms=30000\n"
        b"2026-06-06T10:00:01Z ERROR gateway request failed status=500 path=/checkout\n"
    )

    uploaded = await _upload_content(
        client,
        case_id=case_id,
        filename="../incident.log",
        content_type="text/plain",
        content=content,
    )
    file_id = str(uploaded["file_id"])
    assert uploaded["sha256"] == hashlib.sha256(content).hexdigest()
    assert uploaded["size_bytes"] == len(content)
    upload_record = store.get_upload(file_id)
    assert upload_record is not None
    assert upload_record.object_uri.startswith("file://")
    assert upload_record.object_uri.endswith("/incident.log")
    assert "\\" not in upload_record.object_uri

    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={"sha256": uploaded["sha256"]},
    )
    assert complete.status_code == 200, complete.text
    second_complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={"sha256": uploaded["sha256"]},
    )
    assert second_complete.status_code == 200, second_complete.text

    run = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={
            "input_file_ids": [file_id],
            "config": {"default_window_size_seconds": 60},
        },
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["analysis_run_id"]
    status = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "completed"
    assert status.json()["progress"]["files_processed"] == 1
    assert status.json()["progress"]["raw_lines"] == 2
    logs = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/logs")
    assert {item["file_path"] for item in logs.json()["items"]} == {"incident.log"}
    await client.aclose()


@pytest.mark.asyncio
async def test_analysis_failure_records_sanitized_job_event() -> None:
    store = InMemoryStore()
    user = store.register_user(
        email="failure@example.com",
        username="failure",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Failing annotation",
            "issue_description": "Gateway raises during annotation.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "incident_start": None,
            "incident_end": None,
            "timezone": "UTC",
        },
    )

    with pytest.raises(RuntimeError):
        await store.start_analysis(
            case_id=case.id,
            user_id=user.id,
            input_paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            config={"default_window_size_seconds": 60},
            gateway=FailingAnnotationGateway(),
        )

    run = next(run for run in store.runs.values() if run.case_id == case.id)
    assert run.status == "failed"
    assert run.error_message
    assert "gho_secret_token_1234567890" not in run.error_message
    assert "hunter2" not in run.error_message
    events = store.list_job_events(
        case_id=case.id,
        analysis_run_id=run.id,
        step_name="copilot_annotation",
    )
    failed_events = [event for event in events if event.event_type == "failed"]
    assert len(failed_events) == 1
    failed_event = failed_events[0]
    assert failed_event.error_message
    assert "gho_secret_token_1234567890" not in failed_event.error_message
    assert "hunter2" not in failed_event.error_message
    assert failed_event.metadata == {}
    assert run.progress["steps"]["copilot_annotation"]["status"] == "failed"


@pytest.mark.asyncio
async def test_zip_upload_analysis_by_input_file_ids_ingests_archive(tmp_path: Path) -> None:
    client, _, _ = await _authenticated_client(
        Settings(local_object_store_dir=str(tmp_path / "object-store"))
    )
    case_id = await _create_case(client)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "gateway.log",
            "2026-06-06T10:00:00Z ERROR gateway request failed status=500 path=/checkout\n",
        )
        zip_file.writestr(
            "auth/auth.log",
            "2026-06-06T10:00:01Z ERROR auth-service failed to acquire db connection\n",
        )
    content = archive.getvalue()

    uploaded = await _upload_content(
        client,
        case_id=case_id,
        filename="logs.zip",
        content_type="application/zip",
        content=content,
    )
    run = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={
            "input_file_ids": [uploaded["file_id"]],
            "config": {"default_window_size_seconds": 60},
        },
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["analysis_run_id"]
    status = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}")
    assert status.status_code == 200, status.text
    assert status.json()["progress"]["files_processed"] == 2
    assert status.json()["progress"]["raw_lines"] == 2
    logs = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/logs")
    assert {item["file_path"] for item in logs.json()["items"]} == {"auth/auth.log", "gateway.log"}
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_complete_sha_mismatch_returns_conflict(tmp_path: Path) -> None:
    client, _, _ = await _authenticated_client(
        Settings(local_object_store_dir=str(tmp_path / "object-store"))
    )
    case_id = await _create_case(client)
    uploaded = await _upload_content(
        client,
        case_id=case_id,
        filename="payment.log",
        content_type="text/plain",
        content=b"2026-06-06T10:00:00Z ERROR payment-service timeout calling auth-service\n",
    )
    mismatch = await client.post(
        f"/api/cases/{case_id}/uploads/{uploaded['file_id']}/complete",
        json={"sha256": "0" * 64},
    )
    assert mismatch.status_code == 409
    await client.aclose()
