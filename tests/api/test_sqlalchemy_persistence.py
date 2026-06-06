from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from logan_workers.activities.inference import MockCopilotAnnotationGateway

from app.config import Settings
from app.main import create_app
from app.models import tables
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


def _analytics_counts(store: SQLAlchemyStore, run_id: str) -> dict[str, int]:
    with store.session_factory() as session:
        return {
            "raw_files": session.scalar(
                select(func.count())
                .select_from(tables.RawFile)
                .where(tables.RawFile.analysis_run_id == run_id)
            )
            or 0,
            "raw_log_lines": session.scalar(
                select(func.count())
                .select_from(tables.RawLogLine)
                .where(tables.RawLogLine.analysis_run_id == run_id)
            )
            or 0,
            "normalized_log_lines": session.scalar(
                select(func.count())
                .select_from(tables.NormalizedLogLine)
                .where(tables.NormalizedLogLine.analysis_run_id == run_id)
            )
            or 0,
            "log_templates": session.scalar(
                select(func.count())
                .select_from(tables.LogTemplate)
                .where(tables.LogTemplate.analysis_run_id == run_id)
            )
            or 0,
            "representative_samples": session.scalar(
                select(func.count())
                .select_from(tables.RepresentativeSample)
                .join(
                    tables.LogTemplate,
                    tables.RepresentativeSample.template_id == tables.LogTemplate.id,
                )
                .where(tables.LogTemplate.analysis_run_id == run_id)
            )
            or 0,
            "template_annotations": session.scalar(
                select(func.count())
                .select_from(tables.TemplateAnnotation)
                .where(tables.TemplateAnnotation.analysis_run_id == run_id)
            )
            or 0,
            "time_window_signals": session.scalar(
                select(func.count())
                .select_from(tables.TimeWindowSignal)
                .where(tables.TimeWindowSignal.analysis_run_id == run_id)
            )
            or 0,
            "causal_nodes": session.scalar(
                select(func.count())
                .select_from(tables.CausalNode)
                .where(tables.CausalNode.analysis_run_id == run_id)
            )
            or 0,
            "causal_edges": session.scalar(
                select(func.count())
                .select_from(tables.CausalEdge)
                .where(tables.CausalEdge.analysis_run_id == run_id)
            )
            or 0,
            "causal_summaries": session.scalar(
                select(func.count())
                .select_from(tables.CausalSummary)
                .where(tables.CausalSummary.analysis_run_id == run_id)
            )
            or 0,
        }


def _run_raw_file_ids(store: SQLAlchemyStore, run_id: str) -> set[str]:
    with store.session_factory() as session:
        return set(
            session.scalars(
                select(tables.RawFile.id).where(tables.RawFile.analysis_run_id == run_id)
            ).all()
        )


def _annotation_raw_responses(store: SQLAlchemyStore, run_id: str) -> list[dict[str, object]]:
    with store.session_factory() as session:
        return list(
            session.scalars(
                select(tables.TemplateAnnotation.raw_model_response).where(
                    tables.TemplateAnnotation.analysis_run_id == run_id
                )
            ).all()
        )


def _redacted_raw_log_line_count(store: SQLAlchemyStore, run_id: str) -> int:
    with store.session_factory() as session:
        return (
            session.scalar(
                select(func.count(tables.RawLogLine.raw_text_redacted)).where(
                    tables.RawLogLine.analysis_run_id == run_id
                )
            )
            or 0
        )


def _raw_file_analysis_run_id(store: SQLAlchemyStore, file_id: str) -> str | None:
    with store.session_factory() as session:
        return session.scalar(
            select(tables.RawFile.analysis_run_id).where(tables.RawFile.id == file_id)
        )


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
    progress = status.json()["progress"]
    assert progress["templates"] > 0
    assert _raw_file_analysis_run_id(recreated_store, file_id) is None
    persisted_result = recreated_store.get_analysis_result(case_id, run_id)
    assert persisted_result is not None
    assert persisted_result.model_inputs == []

    analytics_counts = _analytics_counts(recreated_store, run_id)
    assert analytics_counts["raw_files"] > 0
    assert analytics_counts["raw_log_lines"] == progress["normalized_lines"]
    assert _redacted_raw_log_line_count(recreated_store, run_id) > 0
    assert analytics_counts["normalized_log_lines"] == progress["normalized_lines"]
    assert analytics_counts["log_templates"] == progress["templates"]
    assert analytics_counts["representative_samples"] == progress["representative_samples"]
    assert analytics_counts["template_annotations"] == progress["annotated_templates"]
    assert analytics_counts["time_window_signals"] > 0
    assert analytics_counts["causal_nodes"] > 0
    assert analytics_counts["causal_edges"] > 0
    assert analytics_counts["causal_summaries"] == 1

    annotation_responses = _annotation_raw_responses(recreated_store, run_id)
    assert annotation_responses
    assert all(annotation_responses)
    serialized_responses = json.dumps(annotation_responses, sort_keys=True)
    assert "case_context" not in serialized_responses
    assert "representative_lines" not in serialized_responses
    assert "template_context" not in serialized_responses
    assert "model_inputs" not in serialized_responses

    case_record = recreated_store.get_case(case_id)
    assert case_record is not None
    recreated_store._complete_analysis_run(
        run_id=run_id,
        result=persisted_result,
        user_id=case_record.created_by,
    )
    assert _analytics_counts(recreated_store, run_id) == analytics_counts

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


@pytest.mark.asyncio
async def test_sqlalchemy_fanout_scopes_raw_file_ids_per_run(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(database_url=database_url, store_backend="sqlalchemy")
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="repeat.engineer@example.com",
        username="repeat-engineer",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Repeated checkout fixture analysis",
            "issue_description": "Run the same input paths twice.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "timezone": "UTC",
        },
    )
    input_paths = [str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))]

    first = await store.start_analysis(
        case_id=case.id,
        user_id=user.id,
        input_paths=input_paths,
        config={"default_window_size_seconds": 60},
        gateway=MockCopilotAnnotationGateway(),
    )
    second = await store.start_analysis(
        case_id=case.id,
        user_id=user.id,
        input_paths=input_paths,
        config={"default_window_size_seconds": 60},
        gateway=MockCopilotAnnotationGateway(),
    )

    assert first.status == "completed"
    assert second.status == "completed"
    first_counts = _analytics_counts(store, first.id)
    second_counts = _analytics_counts(store, second.id)
    assert first_counts["raw_files"] > 0
    assert second_counts["raw_files"] > 0
    assert first_counts["normalized_log_lines"] > 0
    assert second_counts["normalized_log_lines"] > 0
    assert _run_raw_file_ids(store, first.id).isdisjoint(_run_raw_file_ids(store, second.id))


def test_create_store_auto_uses_sqlalchemy_when_database_url_is_set(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    store = create_store(Settings(database_url=database_url, store_backend="auto"))
    assert isinstance(store, SQLAlchemyStore)
