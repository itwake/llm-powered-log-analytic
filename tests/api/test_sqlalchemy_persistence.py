from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from logan_workers.activities.inference import MockCopilotAnnotationGateway

from app.config import Settings
from app.core.security import decrypt_token
from app.main import create_app
from app.models import tables
from app.services.copilot_auth_service import MockGitHubDeviceClient
from app.sqlalchemy_store import SQLAlchemyStore
from app.store import RAW_LOG_RETAINED_MARKER, create_store


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


def _clear_result_json(store: SQLAlchemyStore, run_id: str) -> None:
    with store.session_factory() as session:
        run = session.get(tables.AnalysisRun, run_id)
        assert run is not None
        run.result_json = None
        session.commit()


def test_sqlalchemy_credentials_persist_expiration_and_revocation(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(database_url=database_url, store_backend="sqlalchemy")
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="credential-persistence@example.com",
        username="credential-persistence",
        full_name=None,
        password="password123",
    )
    future_expires_at = datetime(2035, 1, 1, tzinfo=UTC)

    saved_plugin = store.save_credential(
        user_id=user.id,
        credential_type="copilot_plugin_token",
        token="persisted-plugin-token",
        github_base_url="https://github.com",
        expires_at=future_expires_at,
    )

    assert saved_plugin.expires_at == future_expires_at
    with store.session_factory() as session:
        row = session.scalar(
            select(tables.CopilotCredential).where(
                tables.CopilotCredential.id == saved_plugin.id
            )
        )
        assert row is not None
        row_expires_at = row.expires_at
        assert row_expires_at is not None
        if row_expires_at.tzinfo is None:
            row_expires_at = row_expires_at.replace(tzinfo=UTC)
        assert row_expires_at == future_expires_at

    active_plugin = store.get_credential(
        user_id=user.id, credential_type="copilot_plugin_token"
    )
    assert active_plugin is not None
    assert decrypt_token(
        active_plugin.encrypted_token, store.settings.credential_encryption_key
    ) == "persisted-plugin-token"
    assert store.has_credential(user.id) is True

    store.save_credential(
        user_id=user.id,
        credential_type="copilot_plugin_token",
        token="expired-plugin-token",
        github_base_url="https://github.com",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    assert store.get_credential(user_id=user.id, credential_type="copilot_plugin_token") is None
    assert store.has_credential(user.id) is False

    store.save_credential(
        user_id=user.id,
        credential_type="github_source_oauth",
        token="gho_persisted_source_token",
        github_base_url="https://github.com",
    )
    assert store.has_credential(user.id) is True

    assert store.revoke_credentials(user.id) == 2
    assert store.get_credential(user_id=user.id, credential_type="github_source_oauth") is None
    assert store.get_credential(user_id=user.id, credential_type="copilot_plugin_token") is None
    assert store.has_credential(user.id) is False


def test_sqlalchemy_store_records_s3_upload_object_uri(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        object_store_backend="s3",
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="s3-persistence@example.com",
        username="s3-persistence",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "S3 upload persistence",
            "issue_description": None,
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "incident_start": None,
            "incident_end": None,
            "timezone": "UTC",
        },
    )

    upload = store.create_upload(
        case_id=case.id,
        filename="../incident.log",
        content_type="text/plain",
        size_bytes=10,
    )

    assert upload.object_uri == f"s3://logan/cases/{case.id}/uploads/{upload.id}/incident.log"


def test_sqlalchemy_store_persists_upload_metadata(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        object_store_backend="s3",
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="multipart-persistence@example.com",
        username="multipart-persistence",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Multipart upload persistence",
            "issue_description": None,
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "incident_start": None,
            "incident_end": None,
            "timezone": "UTC",
        },
    )
    upload = store.create_upload(
        case_id=case.id,
        filename="incident.log",
        content_type="text/plain",
        size_bytes=12,
    )

    store.update_upload_metadata(
        upload_id=upload.id,
        metadata={
            "upload_mode": "multipart",
            "multipart_upload_id": "multipart-1",
            "part_size_bytes": 5,
            "part_count": 3,
        },
    )
    recreated = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    persisted = recreated.get_upload(upload.id)

    assert persisted is not None
    assert persisted.upload_metadata == {
        "upload_mode": "multipart",
        "multipart_upload_id": "multipart-1",
        "part_size_bytes": 5,
        "part_count": 3,
    }


def test_sqlalchemy_case_collaborators_persist_and_filter_access(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(database_url=database_url, store_backend="sqlalchemy")
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    owner = store.register_user(
        email="sql-owner@example.com",
        username="sql-owner",
        full_name="SQL Owner",
        password="password123",
    )
    collaborator = store.register_user(
        email="sql-collab@example.com",
        username="sql-collab",
        full_name="SQL Collaborator",
        password="password123",
    )
    outsider = store.register_user(
        email="sql-outsider@example.com",
        username="sql-outsider",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=owner.id,
        data={
            "title": "SQL RBAC case",
            "issue_description": None,
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "incident_start": None,
            "incident_end": None,
            "timezone": "UTC",
        },
    )

    owner_collaborators = store.list_case_collaborators(case.id)
    assert [(item.user_id, item.role) for item in owner_collaborators] == [(owner.id, "owner")]
    assert store.user_can_access_case(owner.id, case.id, "owner") is True
    assert store.user_can_access_case(collaborator.id, case.id, "view") is False
    assert store.list_cases_for_user(collaborator)[1] == 0

    added = store.upsert_case_collaborator(
        case_id=case.id,
        user_id=collaborator.id,
        role="editor",
        added_by=owner.id,
    )
    assert added.role == "editor"
    recreated = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    assert recreated.user_can_access_case(collaborator.id, case.id, "view") is True
    assert recreated.user_can_access_case(collaborator.id, case.id, "edit") is True
    assert recreated.user_can_access_case(collaborator.id, case.id, "owner") is False
    items, total = recreated.list_cases_for_user(collaborator)
    assert total == 1
    assert items[0].id == case.id
    assert recreated.list_cases_for_user(outsider)[1] == 0

    assert recreated.remove_case_collaborator(
        case_id=case.id,
        user_id=collaborator.id,
        removed_by=owner.id,
    ) is True
    assert recreated.user_can_access_case(collaborator.id, case.id, "view") is False
    actions = {record.action for record in recreated.list_audit_logs(case_id=case.id)}
    assert {"case.collaborator.add", "case.collaborator.remove"}.issubset(actions)


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
    events = recreated_store.list_job_events(case_id=case_id, analysis_run_id=run_id)
    assert [event.created_at for event in events] == sorted(event.created_at for event in events)
    assert [event.step_name for event in events if event.event_type == "completed"] == PIPELINE_STEPS
    assert all(event.case_id == case_id for event in events)
    assert all(event.analysis_run_id == run_id for event in events)
    serialized_event_metadata = json.dumps(
        [event.metadata for event in events],
        sort_keys=True,
    )
    assert "model_inputs" not in serialized_event_metadata
    assert "representative_lines" not in serialized_event_metadata
    artifacts = recreated_store.list_analysis_step_artifacts(
        case_id=case_id,
        analysis_run_id=run_id,
    )
    assert [artifact.step_name for artifact in artifacts] == PIPELINE_STEPS
    assert {artifact.artifact_type for artifact in artifacts} == {"step_manifest"}
    assert all(artifact.object_uri.startswith("file://") for artifact in artifacts)
    assert all(len(artifact.sha256) == 64 for artifact in artifacts)
    serialized_artifact_metadata = json.dumps(
        [artifact.metadata for artifact in artifacts],
        sort_keys=True,
    ).lower()
    for forbidden in (
        "raw_text",
        "raw_text_redacted",
        "model_inputs",
        "prompt",
        "token",
        "secret",
        "cookie",
        "representative_lines",
    ):
        assert forbidden not in serialized_artifact_metadata
    duplicate = recreated_store.record_job_event(
        case_id=case_id,
        analysis_run_id=run_id,
        step_name="manual_idempotency",
        event_type="completed",
        status="completed",
        idempotency_key="manual-idempotency-key",
        metadata={"files": 1},
    )
    duplicate_again = recreated_store.record_job_event(
        case_id=case_id,
        analysis_run_id=run_id,
        step_name="manual_idempotency",
        event_type="completed",
        status="completed",
        idempotency_key="manual-idempotency-key",
        metadata={"files": 2},
    )
    assert duplicate_again.id == duplicate.id
    assert (
        len(
            recreated_store.list_analysis_step_artifacts(
                case_id=case_id,
                analysis_run_id=run_id,
                step_name="manual_idempotency",
            )
        )
        == 1
    )
    with recreated_store.session_factory() as session:
        duplicate_count = session.scalar(
            select(func.count())
            .select_from(tables.JobEvent)
            .where(
                tables.JobEvent.analysis_run_id == run_id,
                tables.JobEvent.idempotency_key == "manual-idempotency-key",
                tables.JobEvent.event_type == "completed",
            )
        )
        artifact_duplicate_count = session.scalar(
            select(func.count())
            .select_from(tables.AnalysisStepArtifact)
            .where(
                tables.AnalysisStepArtifact.analysis_run_id == run_id,
                tables.AnalysisStepArtifact.step_name == "manual_idempotency",
                tables.AnalysisStepArtifact.artifact_type == "step_manifest",
            )
        )
    assert duplicate_count == 1
    assert artifact_duplicate_count == 1
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


@pytest.mark.asyncio
async def test_sqlalchemy_report_endpoints_read_fanout_without_result_json(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(database_url=database_url, store_backend="sqlalchemy")
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="fanout-reports@example.com",
        username="fanout-reports",
        full_name=None,
        password="password123",
    )
    token, _session = store.create_session(user.id)
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Checkout reports from fanout",
            "issue_description": "Report endpoints should not need result_json.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "timezone": "UTC",
        },
    )
    secret_log = tmp_path / "secret-payment.log"
    secret_log.write_text(
        (
            "2026-06-06T10:12:30Z ERROR payment-service timeout calling auth-service "
            "after 30000ms Authorization=Bearer raw-secret-token password=hunter2 "
            "request_id=req-secret\n"
        ),
        encoding="utf-8",
    )
    input_paths = [str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))]
    input_paths.append(str(secret_log))
    run = await store.start_analysis(
        case_id=case.id,
        user_id=user.id,
        input_paths=input_paths,
        config={"default_window_size_seconds": 60},
        gateway=MockCopilotAnnotationGateway(),
    )
    assert run.status == "completed"
    assert store.get_analysis_result(case.id, run.id) is not None

    _clear_result_json(store, run.id)
    assert store.get_analysis_result(case.id, run.id) is None

    client = await _client(store)
    client.cookies.set("logan_session", token)
    summary = await client.get(f"/api/cases/{case.id}/analysis-runs/{run.id}/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["items"]
    assert summary.json()["reduction"]["raw_log_lines"] > 0

    temporal = await client.get(f"/api/cases/{case.id}/analysis-runs/{run.id}/temporal")
    assert temporal.status_code == 200, temporal.text
    assert temporal.json()["series"]

    logs = await client.get(
        f"/api/cases/{case.id}/analysis-runs/{run.id}/logs",
        params={"q": "auth-service", "service": "payment-service"},
    )
    assert logs.status_code == 200, logs.text
    logs_body = logs.json()
    assert logs_body["items"]
    assert logs_body["facets"]["service"]
    serialized_logs = json.dumps(logs_body, sort_keys=True)
    assert "raw-secret-token" not in serialized_logs
    assert "hunter2" not in serialized_logs
    assert "raw_text" not in serialized_logs
    assert "raw_message" not in serialized_logs
    assert any("<TOKEN>" in item["message"] for item in logs_body["items"])
    assert any("<SECRET>" in item["message"] for item in logs_body["items"])

    graph = await client.get(f"/api/cases/{case.id}/analysis-runs/{run.id}/causal-graph")
    assert graph.status_code == 200, graph.text
    graph_body = graph.json()
    assert graph_body["nodes"]
    assert graph_body["edges"]
    node_ids = {node["id"] for node in graph_body["nodes"]}
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in graph_body["edges"])
    assert all(edge["needs_validation"] for edge in graph_body["edges"])
    assert graph_body["root_cause_candidates"]

    causal_summary = await client.get(
        f"/api/cases/{case.id}/analysis-runs/{run.id}/causal-summary"
    )
    assert causal_summary.status_code == 200, causal_summary.text
    assert "candidate" in causal_summary.json()["summary_markdown"].lower()
    assert causal_summary.json()["evidence_refs"]
    assert causal_summary.json()["edited"] is False
    await client.aclose()


@pytest.mark.asyncio
async def test_sqlalchemy_retention_scrubs_raw_text_and_preserves_reports(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        audit_retention_days=30,
        raw_log_retention_days=30,
        report_retention_days=30,
    )
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="retention@example.com",
        username="retention",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Retention case",
            "issue_description": "Old rows should be retained safely.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "timezone": "UTC",
        },
    )
    run = await store.start_analysis(
        case_id=case.id,
        user_id=user.id,
        input_paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
        config={"default_window_size_seconds": 60},
        gateway=MockCopilotAnnotationGateway(),
    )
    assert run.status == "completed"
    result = store.get_analysis_result(case.id, run.id)
    assert result is not None
    export_artifact = result.exports["json"]
    store.create_export(
        export_id=export_artifact.export_id,
        case_id=case.id,
        analysis_run_id=run.id,
        export_type="json",
        object_uri=export_artifact.object_uri,
        user_id=user.id,
    )

    now = datetime(2026, 6, 6, tzinfo=UTC)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    recent = datetime(2026, 6, 1, tzinfo=UTC)
    with store.session_factory() as session:
        raw_count = session.scalar(
            select(func.count())
            .select_from(tables.RawLogLine)
            .where(tables.RawLogLine.analysis_run_id == run.id)
        )
        normalized_count = session.scalar(
            select(func.count())
            .select_from(tables.NormalizedLogLine)
            .where(tables.NormalizedLogLine.analysis_run_id == run.id)
        )
        artifact_count = session.scalar(
            select(func.count())
            .select_from(tables.AnalysisStepArtifact)
            .where(tables.AnalysisStepArtifact.analysis_run_id == run.id)
        )
        assert raw_count and raw_count > 0
        assert normalized_count and normalized_count > 0
        assert artifact_count == len(PIPELINE_STEPS)
        session.execute(delete(tables.AuditLog))
        session.add_all(
            [
                tables.AuditLog(
                    id="00000000-0000-0000-0000-000000000001",
                    action="old.audit",
                    metadata_json={},
                    created_at=old,
                ),
                tables.AuditLog(
                    id="00000000-0000-0000-0000-000000000002",
                    action="recent.audit",
                    metadata_json={},
                    created_at=recent,
                ),
            ]
        )
        run_row = session.get(tables.AnalysisRun, run.id)
        assert run_row is not None
        run_row.started_at = old
        run_row.completed_at = old
        export_row = session.get(tables.Export, export_artifact.export_id)
        assert export_row is not None
        export_row.created_at = old
        for raw_line in session.scalars(
            select(tables.RawLogLine).where(tables.RawLogLine.analysis_run_id == run.id)
        ):
            raw_line.created_at = old
        for artifact in session.scalars(
            select(tables.AnalysisStepArtifact).where(
                tables.AnalysisStepArtifact.analysis_run_id == run.id
            )
        ):
            artifact.created_at = old
        session.commit()

    retention = store.run_retention(now=now)

    assert retention.audit_logs_deleted == 1
    assert retention.raw_log_lines_scrubbed == raw_count
    assert retention.exports_deleted == 1
    assert retention.analysis_results_cleared == 1
    assert retention.step_artifacts_deleted == artifact_count
    assert store.get_export(export_artifact.export_id) is None
    assert store.get_analysis_result(case.id, run.id) is None
    assert store.list_analysis_step_artifacts(case_id=case.id, analysis_run_id=run.id) == []

    with store.session_factory() as session:
        remaining_audits = session.scalars(select(tables.AuditLog.action)).all()
        assert remaining_audits == ["recent.audit"]
        raw_values = session.scalars(
            select(tables.RawLogLine.raw_text).where(tables.RawLogLine.analysis_run_id == run.id)
        ).all()
        raw_redacted_values = session.scalars(
            select(tables.RawLogLine.raw_text_redacted).where(
                tables.RawLogLine.analysis_run_id == run.id
            )
        ).all()
        assert set(raw_values) == {RAW_LOG_RETAINED_MARKER}
        assert set(raw_redacted_values) == {RAW_LOG_RETAINED_MARKER}
        assert (
            session.scalar(
                select(func.count())
                .select_from(tables.NormalizedLogLine)
                .where(tables.NormalizedLogLine.analysis_run_id == run.id)
            )
            == normalized_count
        )

    summary = store.get_report_summary(case_id=case.id, run_id=run.id)
    logs = store.get_report_logs(case_id=case.id, run_id=run.id, limit=5)
    causal_summary = store.get_report_causal_summary(case_id=case.id, run_id=run.id)
    causal_graph = store.get_report_causal_graph(case_id=case.id, run_id=run.id)
    assert summary is not None and summary["items"]
    assert logs is not None and logs["items"]
    assert causal_summary is not None and causal_summary["evidence_refs"]
    assert causal_graph is not None and causal_graph["nodes"]


def test_create_store_auto_uses_sqlalchemy_when_database_url_is_set(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    store = create_store(Settings(database_url=database_url, store_backend="auto"))
    assert isinstance(store, SQLAlchemyStore)
