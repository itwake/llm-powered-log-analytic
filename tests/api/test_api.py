from __future__ import annotations

import hashlib
import io
import json
from collections.abc import AsyncIterator
from pathlib import Path
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from logan_workers.activities.inference import MockAIPlatformAnnotationGateway

from app.config import Settings
from app.main import create_app
from app.services.model_gateway import ModelTransportError
from app.store import DEFAULT_ORGANIZATION_ID, InMemoryStore, merge_analysis_result_progress


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")
PIPELINE_STEPS = [
    "ingest_paths",
    "merge_entries",
    "preprocess_redact",
    "drain_templating",
    "representative_sampling",
    "ai_platform_annotation",
    "broadcast_annotations",
    "temporal_aggregation",
    "causal_graph",
    "causal_summary",
    "export_artifacts",
]


def test_merge_analysis_result_progress_preserves_orchestrator() -> None:
    assert merge_analysis_result_progress(
        {"current_step": "workflow_start", "orchestrator": "temporal"},
        {"current_step": "completed", "files_processed": 3},
    ) == {
        "current_step": "completed",
        "files_processed": 3,
        "orchestrator": "temporal",
    }


def test_job_event_progress_logs_are_safe(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryStore()

    with caplog.at_level("INFO", logger="logan.analysis.progress"):
        event = store.record_job_event(
            case_id="case-1",
            analysis_run_id="run-1",
            step_name="ingest_paths",
            event_type="completed",
            status="completed",
            idempotency_key="ingest_paths:completed:1",
            metadata={
                "files": 2,
                "raw_lines": 100,
                "authorization": "Bearer bearer-secret-token-1234567890",
                "input_path": "/tmp/secret.log",
                "token": "gho_SECRET12345678",
                "export_types": ["json", "markdown", "unsafe"],
                "artifacts": {"safe_count": 1, "prompt": "raw prompt"},
            },
            error_message="failed token=gho_SECRET12345678 at /tmp/secret.log",
        )

    records = [record for record in caplog.records if record.name == "logan.analysis.progress"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "analysis_event case_id=case-1" in message
    assert "step=ingest_paths" in message
    assert '"raw_lines":100' in message
    assert "gho_SECRET12345678" not in message
    assert "/tmp/secret.log" not in message
    extra = records[0].logan_analysis_event
    assert extra["metadata"] == {
        "files": 2,
        "raw_lines": 100,
        "export_types": ["json", "markdown"],
        "artifacts": {"safe_count": 1},
    }
    assert extra["error_message"] == "failed token=<REDACTED> at <PATH>"
    assert event.metadata == extra["metadata"]

    caplog.clear()
    with caplog.at_level("INFO", logger="logan.analysis.progress"):
        duplicate = store.record_job_event(
            case_id="case-1",
            analysis_run_id="run-1",
            step_name="ingest_paths",
            event_type="completed",
            status="completed",
            idempotency_key="ingest_paths:completed:1",
            metadata={"files": 99},
        )

    assert duplicate.id == event.id
    assert [record for record in caplog.records if record.name == "logan.analysis.progress"] == []


@pytest.mark.asyncio
async def test_cors_allowed_origins_are_configurable() -> None:
    app_settings = Settings(cors_allowed_origins="https://logan.example.com, http://localhost:3000")
    app = create_app(
        store=InMemoryStore(app_settings),        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.options(
            "/api/auth/me",
            headers={
                "Origin": "https://logan.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://logan.example.com"


class FailingAnnotationGateway(MockAIPlatformAnnotationGateway):
    async def responses(self, **kwargs):
        raise RuntimeError(
            "annotation failed source_token=gho_secret_token_1234567890 "
            "password=hunter2"
        )


class StreamingChatGateway(MockAIPlatformAnnotationGateway):
    async def responses(self, **kwargs):
        if kwargs.get("stream"):
            self.calls.append(kwargs)

            async def stream() -> AsyncIterator[dict[str, object]]:
                yield {"type": "message.delta", "delta": "Auth-service "}
                yield {"type": "message.delta", "delta": "is candidate evidence."}
                yield {
                    "type": "message.completed",
                    "output_text": "Auth-service is candidate evidence.",
                }

            return stream()
        return await super().responses(**kwargs)


class StreamingErrorGateway(MockAIPlatformAnnotationGateway):
    async def responses(self, **kwargs):
        if kwargs.get("stream"):
            raise ModelTransportError(
                "stream failed source_token=gho_secret_token_1234567890 password=hunter2"
            )
        return await super().responses(**kwargs)


class FakeS3NotFound(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.complete_objects: dict[tuple[str, str, str], dict[str, object]] = {}
        self.uploaded_parts: dict[tuple[str, str, str], list[dict[str, object]]] = {}
        self.presign_calls: list[dict[str, object]] = []
        self.head_calls: list[dict[str, str]] = []
        self.download_calls: list[dict[str, str]] = []
        self.get_object_calls: list[dict[str, str]] = []
        self.create_multipart_calls: list[dict[str, object]] = []
        self.complete_multipart_calls: list[dict[str, object]] = []
        self.abort_multipart_calls: list[dict[str, str]] = []
        self.list_parts_calls: list[dict[str, object]] = []
        self._upload_counter = 0

    def generate_presigned_url(self, operation: str, **kwargs: object) -> str:
        self.presign_calls.append({"operation": operation, **kwargs})
        params = kwargs.get("Params")
        assert isinstance(params, dict)
        signature = f"fake-{len(self.presign_calls)}"
        if operation == "upload_part":
            return (
                f"https://minio.example/{params['Bucket']}/{params['Key']}"
                f"?uploadId={params['UploadId']}&partNumber={params['PartNumber']}"
                f"&signature={signature}"
            )
        return f"https://minio.example/{params['Bucket']}/{params['Key']}?signature={signature}"

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.head_calls.append({"Bucket": Bucket, "Key": Key})
        try:
            return self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise FakeS3NotFound() from exc

    def _object_body(self, *, Bucket: str, Key: str) -> bytes:
        body = self.objects[(Bucket, Key)].get("Body", b"")
        if isinstance(body, bytes):
            return body
        if isinstance(body, bytearray):
            return bytes(body)
        if hasattr(body, "read"):
            content = body.read()
            return bytes(content)
        return bytes(str(body), encoding="utf-8")

    def download_file(self, *, Bucket: str, Key: str, Filename: str) -> None:
        self.download_calls.append({"Bucket": Bucket, "Key": Key, "Filename": Filename})
        Path(Filename).write_bytes(self._object_body(Bucket=Bucket, Key=Key))

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.get_object_calls.append({"Bucket": Bucket, "Key": Key})
        return {"Body": io.BytesIO(self._object_body(Bucket=Bucket, Key=Key))}

    def create_multipart_upload(self, **kwargs: object) -> dict[str, object]:
        self._upload_counter += 1
        upload_id = f"multipart-{self._upload_counter}"
        self.create_multipart_calls.append({**kwargs, "UploadId": upload_id})
        return {"UploadId": upload_id}

    def list_parts(self, **kwargs: object) -> dict[str, object]:
        self.list_parts_calls.append(dict(kwargs))
        key = (str(kwargs["Bucket"]), str(kwargs["Key"]), str(kwargs["UploadId"]))
        return {"Parts": self.uploaded_parts.get(key, [])}

    def complete_multipart_upload(self, **kwargs: object) -> dict[str, object]:
        self.complete_multipart_calls.append(dict(kwargs))
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        upload_id = str(kwargs["UploadId"])
        completed_object = self.complete_objects.get((bucket, key, upload_id))
        if completed_object is not None:
            self.objects[(bucket, key)] = completed_object
        return {"Bucket": bucket, "Key": key, "UploadId": upload_id}

    def abort_multipart_upload(self, **kwargs: str) -> dict[str, object]:
        self.abort_multipart_calls.append(dict(kwargs))
        return {}


async def _authenticated_client(
    app_settings: Settings | None = None,
    s3_client_factory=None,
    model_gateway=None,
) -> tuple[AsyncClient, InMemoryStore, str]:
    store = InMemoryStore(app_settings or Settings())
    app = create_app(
        store=store,
        model_gateway=model_gateway or MockAIPlatformAnnotationGateway(),
        s3_client_factory=s3_client_factory,
    )
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    user = store.register_user(
        email="engineer@example.com",
        username="engineer",
        full_name="LogAn Engineer",
        password="password123",
    )
    token, _ = store.create_session(user.id)
    client.cookies.set("logan_session", token)
    return client, store, store.users_by_username["engineer"]


async def _register_and_login(
    client: AsyncClient,
    store: InMemoryStore,
    *,
    email: str,
    username: str,
    full_name: str | None = None,
    role: str = "engineer",
) -> str:
    user = store.register_user(
        email=email,
        username=username,
        full_name=full_name,
        password="password123",
    )
    user_id = store.users_by_username[username]
    store.users[user_id].role = role
    token, _ = store.create_session(user.id)
    client.cookies.set("logan_session", token)
    return user_id


def _parse_sse_frames(text: str) -> list[tuple[str, dict[str, object]]]:
    frames: list[tuple[str, dict[str, object]]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:")
                data_lines.append(data[1:] if data.startswith(" ") else data)
        frames.append((event, json.loads("\n".join(data_lines))))
    return frames


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
    assert upload.json()["upload_url"].startswith("/api/cases/")
    put = await client.put(
        upload.json()["upload_url"],
        content=content,
        headers={"content-type": content_type},
    )
    assert put.status_code == 200, put.text
    return put.json()


async def _create_completed_sample_run(client: AsyncClient) -> tuple[str, str]:
    case_id = await _create_case(client)
    run = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={
            "input_paths": [str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            "config": {"default_window_size_seconds": 60},
        },
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["analysis_run_id"]
    status = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "completed"
    return case_id, str(run_id)


@pytest.mark.asyncio
async def test_case_can_be_updated_and_deleted() -> None:
    client, store, _ = await _authenticated_client()
    case_id = await _create_case(client)

    updated = await client.patch(
        f"/api/cases/{case_id}",
        json={
            "title": "Updated checkout incident",
            "issue_description": "Updated customer impact.",
            "product": "commerce-platform",
            "service": "payments",
            "environment": None,
            "timezone": "UTC",
        },
    )
    assert updated.status_code == 200, updated.text
    updated_body = updated.json()
    assert updated_body["title"] == "Updated checkout incident"
    assert updated_body["issue_description"] == "Updated customer impact."
    assert updated_body["service"] == "payments"
    assert updated_body["environment"] is None

    deleted = await client.delete(f"/api/cases/{case_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"status": "deleted", "deleted": True}
    assert (await client.get(f"/api/cases/{case_id}")).status_code == 404
    cases = await client.get("/api/cases")
    assert cases.status_code == 200
    assert cases.json()["total"] == 0

    audit_actions = {record.action for record in store.list_audit_logs(case_id=case_id)}
    assert {"case.update", "case.delete"}.issubset(audit_actions)
    await client.aclose()


@pytest.mark.asyncio
async def test_analysis_run_can_be_cancelled() -> None:
    client, store, user_id = await _authenticated_client()
    case_id = await _create_case(client)
    run = store.create_analysis_run(
        case_id=case_id,
        user_id=user_id,
        config={"default_window_size_seconds": 60},
    )

    cancelled = await client.post(f"/api/cases/{case_id}/analysis-runs/{run.id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    cancelled_body = cancelled.json()
    assert cancelled_body["analysis_run_id"] == run.id
    assert cancelled_body["status"] == "cancelled"
    assert cancelled_body["current_step"] == "cancelled"
    assert cancelled_body["completed_at"] is not None

    events = await client.get(f"/api/cases/{case_id}/analysis-runs/{run.id}/events")
    assert events.status_code == 200, events.text
    assert [item["event_type"] for item in events.json()["items"]] == ["cancelled"]
    assert store.get_case(case_id).status == "cancelled"
    assert {record.action for record in store.list_audit_logs(case_id=case_id)} >= {
        "analysis.start",
        "analysis.cancel",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint_records_safe_api_request_metrics() -> None:
    store = InMemoryStore(Settings(metrics_enabled=True))
    app = create_app(
        store=store,
        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")

    response = await client.get("/api/capabilities")
    assert response.status_code == 200

    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["content-type"]
    assert "version=" in metrics.headers["content-type"]
    body = metrics.text
    assert (
        'logan_http_requests_total{method="GET",route="/api/capabilities",status_code="200"}'
        in body
    )
    assert "gho_metrics_secret_token_123456" not in body
    assert "postgresql+psycopg://logan:secret@postgres:5432/logan" not in body
    assert "logan-secret" not in body
    assert "Checkout API intermittent 500 errors" not in body
    await client.aclose()


@pytest.mark.asyncio
async def test_temporal_start_path_passes_safe_workflow_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_start_analyze_case_workflow(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "logan_workers.temporal_client.start_analyze_case_workflow",
        fake_start_analyze_case_workflow,
    )
    client, store, _ = await _authenticated_client(
        Settings(
            analysis_orchestrator="temporal",
            temporal_address="temporal.test:7233",
            temporal_namespace="logan-test",
            temporal_task_queue="logan-analysis-test",
            temporal_activity_start_to_close_seconds=17,
            temporal_activity_max_attempts=4,
            database_url="postgresql+psycopg://logan:secret@postgres/logan",
            github_source_token="gho_source_secret_1234567890",
            ai_platform_token="ai_platform_secret_1234567890",
            s3_access_key="access-key",
            s3_secret_key="secret-key",
        )
    )
    case_id = await _create_case(client)

    response = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={
            "input_paths": [str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            "config": {
                "default_window_size_seconds": 60,
                "model": {"model": "gpt-5.4"},
                "api_key": "sk-should-not-enter-history",
                "database_url": "postgresql://secret",
                "nested": {
                    "keep": 1,
                    "source_token": "gho_nested_secret_1234567890",
                },
            },
        },
    )

    assert response.status_code == 200, response.text
    run_id = response.json()["analysis_run_id"]
    run = store.get_analysis_run(run_id)
    assert run is not None
    assert run.status == "processing"
    assert run.progress == {"current_step": "workflow_start", "orchestrator": "temporal"}
    assert captured["case_id"] == case_id
    assert captured["analysis_run_id"] == run_id
    assert captured["activity_start_to_close_seconds"] == 17
    assert captured["activity_max_attempts"] == 4
    workflow_config = captured["config"]
    assert isinstance(workflow_config, dict)
    assert workflow_config["model"] == {"model": "gpt-5.4"}
    assert workflow_config["nested"] == {"keep": 1}
    assert "api_key" not in workflow_config
    assert "database_url" not in workflow_config
    serialized_capture = json.dumps(
        {
            "paths": captured["paths"],
            "case_context": captured["case_context"],
            "config": workflow_config,
        },
        sort_keys=True,
    )
    assert "secret" not in serialized_capture.lower()
    assert "token" not in serialized_capture.lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_api_and_ai_platform_only_auth_surface() -> None:
    client, _, _ = await _authenticated_client()
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401
    await client.aclose()


@pytest.mark.asyncio
async def test_case_rbac_collaborator_roles_are_enforced(tmp_path: Path) -> None:
    store = InMemoryStore(Settings(local_object_store_dir=str(tmp_path / "object-store")))
    app = create_app(
        store=store,
        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    owner = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    collaborator = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    admin = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")

    owner_id = await _register_and_login(
        owner,
        store,
        email="owner@example.com",
        username="owner",
        full_name="Owner",
    )
    collaborator_id = await _register_and_login(
        collaborator,
        store,
        email="collaborator@example.com",
        username="collaborator",
        full_name="Collaborator",
    )
    admin_id = await _register_and_login(
        admin,
        store,
        email="admin@example.com",
        username="admin",
        full_name="Admin",
        role="admin",
    )

    case_id = await _create_case(owner)
    run = await owner.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={
            "input_paths": [str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            "config": {"default_window_size_seconds": 60},
        },
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["analysis_run_id"]

    assert (await collaborator.get("/api/cases")).json()["total"] == 0
    assert (await collaborator.get(f"/api/cases/{case_id}")).status_code == 404
    assert (await anonymous.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/artifacts")).status_code == 401
    assert (await collaborator.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/artifacts")).status_code == 404
    forbidden_upload = await collaborator.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "blocked.log", "content_type": "text/plain", "size_bytes": 10},
    )
    assert forbidden_upload.status_code == 403

    viewer = await owner.post(
        f"/api/cases/{case_id}/collaborators",
        json={"user_id": collaborator_id, "role": "viewer"},
    )
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["role"] == "viewer"
    collaborators = await owner.get(f"/api/cases/{case_id}/collaborators")
    assert collaborators.status_code == 200
    assert {item["user_id"] for item in collaborators.json()["items"]} >= {
        owner_id,
        collaborator_id,
    }

    visible_cases = await collaborator.get("/api/cases")
    assert visible_cases.status_code == 200
    assert visible_cases.json()["total"] == 1
    assert (await collaborator.get(f"/api/cases/{case_id}")).status_code == 200
    assert (await collaborator.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/events")).status_code == 200
    assert (await collaborator.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/artifacts")).status_code == 200
    assert (await collaborator.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/summary")).status_code == 200
    viewer_start = await collaborator.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={"input_paths": [], "config": {"default_window_size_seconds": 60}},
    )
    assert viewer_start.status_code == 403
    viewer_feedback = await collaborator.post(
        f"/api/cases/{case_id}/feedback",
        json={
            "analysis_run_id": run_id,
            "target_type": "template",
            "target_id": "template-1",
            "feedback_type": "note",
        },
    )
    assert viewer_feedback.status_code == 403
    viewer_summary_edit = await collaborator.patch(
        f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary",
        json={"summary_markdown": "viewer edit is not allowed"},
    )
    assert viewer_summary_edit.status_code == 403

    editor = await owner.post(
        f"/api/cases/{case_id}/collaborators",
        json={"user_id": collaborator_id, "role": "editor"},
    )
    assert editor.status_code == 200, editor.text
    assert editor.json()["role"] == "editor"
    editor_upload = await collaborator.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "editor.log", "content_type": "text/plain", "size_bytes": 4},
    )
    assert editor_upload.status_code == 200, editor_upload.text
    editor_start = await collaborator.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={"input_paths": [], "config": {"default_window_size_seconds": 60}},
    )
    assert editor_start.status_code == 200, editor_start.text
    editor_manage = await collaborator.post(
        f"/api/cases/{case_id}/collaborators",
        json={"user_id": admin_id, "role": "viewer"},
    )
    assert editor_manage.status_code == 403

    admin_cases = await admin.get("/api/cases")
    assert admin_cases.status_code == 200
    assert admin_cases.json()["total"] == 1
    removed = await admin.delete(f"/api/cases/{case_id}/collaborators/{collaborator_id}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed"] is True
    assert (await collaborator.get(f"/api/cases/{case_id}")).status_code == 404
    added_by_admin = await admin.post(
        f"/api/cases/{case_id}/collaborators",
        json={"user_id": collaborator_id, "role": "viewer"},
    )
    assert added_by_admin.status_code == 200, added_by_admin.text

    audit_actions = {record.action for record in store.list_audit_logs(case_id=case_id)}
    assert {"case.collaborator.add", "case.collaborator.remove"}.issubset(audit_actions)

    await owner.aclose()
    await collaborator.aclose()
    await admin.aclose()
    await anonymous.aclose()


@pytest.mark.asyncio
async def test_organization_isolation_and_policy_group_case_access(tmp_path: Path) -> None:
    store = InMemoryStore(Settings(local_object_store_dir=str(tmp_path / "object-store")))
    store.ensure_organization(
        organization_id="org-two",
        name="Second Organization",
        slug="org-two",
    )
    app = create_app(
        store=store,
        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    owner = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    admin = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    direct = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    group_member = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    outsider = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    org_two_admin = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")

    owner_id = await _register_and_login(
        owner,
        store,
        email="org-owner@example.com",
        username="org-owner",
    )
    admin_id = await _register_and_login(
        admin,
        store,
        email="org-admin@example.com",
        username="org-admin",
        role="admin",
    )
    direct_id = await _register_and_login(
        direct,
        store,
        email="direct-viewer@example.com",
        username="direct-viewer",
    )
    group_member_id = await _register_and_login(
        group_member,
        store,
        email="group-member@example.com",
        username="group-member",
    )
    await _register_and_login(
        outsider,
        store,
        email="same-org-outsider@example.com",
        username="same-org-outsider",
    )
    org_two_user = store.register_user(
        email="org-two-admin@example.com",
        username="org-two-admin",
        full_name=None,
        password="password123",
        organization_id="org-two",
    )
    org_two_user.role = "admin"
    org_two_token, _ = store.create_session(org_two_user.id)
    org_two_admin.cookies.set("logan_session", org_two_token)

    case_id = await _create_case(owner)
    org_two_case = store.create_case(
        user_id=org_two_user.id,
        data={
            "title": "Other org case",
            "issue_description": None,
            "product": "other",
            "service": "other",
            "environment": "prod",
            "incident_start": None,
            "incident_end": None,
            "timezone": "UTC",
        },
    )

    assert (await org_two_admin.get("/api/cases")).json()["total"] == 1
    assert (await org_two_admin.get(f"/api/cases/{case_id}")).status_code == 404
    default_admin_cases = await admin.get("/api/cases")
    assert default_admin_cases.status_code == 200, default_admin_cases.text
    assert {item["case_id"] for item in default_admin_cases.json()["items"]} == {case_id}
    assert (await admin.get(f"/api/cases/{org_two_case.id}")).status_code == 404
    assert (await outsider.get(f"/api/cases/{case_id}")).status_code == 404

    cross_org_collab = await owner.post(
        f"/api/cases/{case_id}/collaborators",
        json={"user_id": org_two_user.id, "role": "viewer"},
    )
    assert cross_org_collab.status_code == 400

    direct_viewer = await owner.post(
        f"/api/cases/{case_id}/collaborators",
        json={"user_id": direct_id, "role": "viewer"},
    )
    assert direct_viewer.status_code == 200, direct_viewer.text
    assert (await direct.get(f"/api/cases/{case_id}")).status_code == 200

    group = await admin.post("/api/admin/policy-groups", json={"name": "SRE Team"})
    assert group.status_code == 200, group.text
    group_id = group.json()["id"]
    member = await admin.post(
        f"/api/admin/policy-groups/{group_id}/members",
        json={"user_id": group_member_id, "role": "viewer"},
    )
    assert member.status_code == 200, member.text
    grant = await admin.post(
        f"/api/admin/cases/{case_id}/policy-groups",
        json={"group_id": group_id, "role": "viewer"},
    )
    assert grant.status_code == 200, grant.text
    assert (await group_member.get(f"/api/cases/{case_id}")).status_code == 200
    viewer_upload = await group_member.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "viewer.log", "content_type": "text/plain", "size_bytes": 0},
    )
    assert viewer_upload.status_code == 403

    editor_grant = await admin.post(
        f"/api/admin/cases/{case_id}/policy-groups",
        json={"group_id": group_id, "role": "editor"},
    )
    assert editor_grant.status_code == 200, editor_grant.text
    editor_upload = await group_member.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "editor.log", "content_type": "text/plain", "size_bytes": 0},
    )
    assert editor_upload.status_code == 200, editor_upload.text
    assert (await outsider.get(f"/api/cases/{case_id}")).status_code == 404

    users = await org_two_admin.get("/api/admin/users")
    assert users.status_code == 200, users.text
    assert {item["id"] for item in users.json()["items"]} == {org_two_user.id}
    default_groups = await admin.get("/api/admin/policy-groups")
    assert default_groups.json()["total"] == 1
    assert default_groups.json()["items"][0]["member_count"] == 1
    org_two_groups = await org_two_admin.get("/api/admin/policy-groups")
    assert org_two_groups.json()["total"] == 0

    audit_actions = {record.action for record in store.list_audit_logs(case_id=case_id)}
    assert {
        "case.policy_group.grant",
        "case.collaborator.add",
    }.issubset(audit_actions)
    assert owner_id
    assert admin_id

    await owner.aclose()
    await admin.aclose()
    await direct.aclose()
    await group_member.aclose()
    await outsider.aclose()
    await org_two_admin.aclose()


@pytest.mark.asyncio
async def test_admin_api_settings_are_safe_and_admin_only() -> None:
    store = InMemoryStore(
        Settings(
            database_url="postgresql://logan:db-secret@postgres/logan",
            github_source_token="gho_source_secret",
            ai_platform_token="ai-platform-secret",
            s3_access_key="access-secret",
            s3_secret_key="s3-secret",
            clickhouse_password="clickhouse-secret",
            opensearch_password="opensearch-secret",
            rate_limit_enabled=False,
        )
    )
    app = create_app(
        store=store,
        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    engineer = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    admin = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    engineer_id = await _register_and_login(
        engineer,
        store,
        email="admin-denied@example.com",
        username="admin-denied",
    )
    admin_id = await _register_and_login(
        admin,
        store,
        email="settings-admin@example.com",
        username="settings-admin",
        role="admin",
    )
    store.record_audit(
        action="unsafe.audit",
        user_id=engineer_id,
        metadata={
            "raw_text": "raw log line should not leave admin API",
            "source_token": "gho_should_not_leave",
            "safe": "ok",
        },
    )

    assert (await engineer.get("/api/admin/users")).status_code == 403
    settings_response = await admin.get("/api/admin/settings")
    assert settings_response.status_code == 200, settings_response.text
    settings_text = settings_response.text.lower()
    for forbidden in (
        "db-secret",
        "gho_source_secret",
        "ai-platform-secret",
        "access-secret",
        "s3-secret",
        "clickhouse-secret",
        "opensearch-secret",
        "database_url",
        "token",
        "password",
        "secret_key",
    ):
        assert forbidden.lower() not in settings_text

    users = await admin.get("/api/admin/users")
    assert users.status_code == 200, users.text
    assert {item["id"] for item in users.json()["items"]} >= {engineer_id, admin_id}
    patched = await admin.patch(
        f"/api/admin/users/{engineer_id}",
        json={"role": "admin", "is_active": False},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["role"] == "admin"
    assert patched.json()["is_active"] is False

    audit_logs = await admin.get("/api/admin/audit-logs", params={"action": "unsafe.audit"})
    assert audit_logs.status_code == 200, audit_logs.text
    assert audit_logs.json()["items"][0]["metadata"] == {"safe": "ok"}
    assert "raw log line" not in audit_logs.text
    assert "gho_should_not_leave" not in audit_logs.text
    store.record_audit(
        action="model.invocation",
        user_id=engineer_id,
        metadata={
            "analysis_run_id": "run-safe",
            "model_provider": "ai_platform",
            "model_name": "gpt-5.4",
            "model_reasoning_effort": "high",
            "prompt_version": "annotation_v1",
            "model_inputs": [{"raw_text": "raw log line should not leave admin API"}],
            "prompt": "classify the raw log line",
            "input_path": "tests/fixtures/logs/checkout_incident/auth.log",
            "representative_lines": [{"message": "secret token"}],
            "template_count": 2,
            "annotation_count": 2,
            "representative_sample_count": 3,
            "model_input_count": 2,
            "redacted": True,
        },
    )
    model_audit_logs = await admin.get(
        "/api/admin/audit-logs", params={"action": "model.invocation"}
    )
    assert model_audit_logs.status_code == 200, model_audit_logs.text
    assert model_audit_logs.json()["items"][0]["metadata"] == {
        "analysis_run_id": "run-safe",
        "model_provider": "ai_platform",
        "model_name": "gpt-5.4",
        "model_reasoning_effort": "high",
        "prompt_version": "annotation_v1",
        "template_count": 2,
        "annotation_count": 2,
        "representative_sample_count": 3,
        "model_input_count": 2,
        "redacted": True,
    }
    assert "classify the raw log line" not in model_audit_logs.text
    assert "tests/fixtures" not in model_audit_logs.text
    assert "secret token" not in model_audit_logs.text

    retention = await admin.post("/api/admin/retention/run")
    assert retention.status_code == 200, retention.text
    assert set(retention.json()) == {
        "audit_logs_deleted",
        "raw_log_lines_scrubbed",
        "exports_deleted",
        "analysis_results_cleared",
        "step_artifacts_deleted",
    }
    assert "admin.retention.run" in {
        record.action for record in store.list_audit_logs(user_id=admin_id)
    }

    await engineer.aclose()
    await admin.aclose()


@pytest.mark.asyncio
async def test_scim_users_and_groups_support_bearer_and_admin_session() -> None:
    store = InMemoryStore(
        Settings(scim_bearer_token="scim-secret", scim_organization_id="scim-org")
    )
    app = create_app(
        store=store,
        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    scim = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"authorization": "Bearer scim-secret"},
    )
    admin = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")

    unauthorized = await anonymous.get("/api/scim/v2/Users")
    assert unauthorized.status_code == 401

    admin_id = await _register_and_login(
        admin,
        store,
        email="scim-admin@example.com",
        username="scim-admin",
        role="admin",
    )
    admin_scim = await admin.get("/api/scim/v2/Users")
    assert admin_scim.status_code == 200, admin_scim.text

    created = await scim.post(
        "/api/scim/v2/Users",
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "ext-user-1",
            "userName": "scim.user@example.com",
            "name": {"formatted": "SCIM User"},
            "emails": [{"value": "scim.user@example.com", "primary": True}],
            "active": True,
        },
    )
    assert created.status_code == 201, created.text
    user_body = created.json()
    scim_user_id = user_body["id"]
    assert user_body["userName"] == "scim.user@example.com"
    assert user_body["active"] is True
    assert store.get_user(scim_user_id).organization_id == "scim-org"
    assert "password" not in created.text.lower()
    assert "token" not in created.text.lower()
    assert "secret" not in created.text.lower()

    bearer_users = await scim.get("/api/scim/v2/Users")
    assert bearer_users.status_code == 200, bearer_users.text
    assert {item["id"] for item in bearer_users.json()["Resources"]} == {scim_user_id}

    admin_users = await admin.get("/api/scim/v2/Users")
    assert admin_users.status_code == 200, admin_users.text
    assert scim_user_id not in {item["id"] for item in admin_users.json()["Resources"]}
    assert admin_id in {item["id"] for item in admin_users.json()["Resources"]}
    assert (await admin.get(f"/api/scim/v2/Users/{scim_user_id}")).status_code == 404
    assert (await scim.get(f"/api/scim/v2/Users/{admin_id}")).status_code == 404

    patched = await scim.patch(
        f"/api/scim/v2/Users/{scim_user_id}",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["active"] is False
    assert store.get_user(scim_user_id).is_active is False

    reactivated = await scim.put(
        f"/api/scim/v2/Users/{scim_user_id}",
        json={
            "userName": "scim.user@example.com",
            "name": {"formatted": "SCIM User Updated"},
            "emails": [{"value": "scim.user@example.com", "primary": True}],
            "active": True,
        },
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["displayName"] == "SCIM User Updated"
    assert store.get_user(scim_user_id).is_active is True

    group = await scim.post(
        "/api/scim/v2/Groups",
        json={
            "displayName": "SCIM Synced Group",
            "members": [{"value": scim_user_id}],
        },
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    assert store.get_policy_group(group_id).organization_id == "scim-org"
    assert [member["value"] for member in group.json()["members"]] == [scim_user_id]
    assert store.list_policy_group_members(group_id)[0].user_id == scim_user_id

    admin_group = await admin.get(f"/api/scim/v2/Groups/{group_id}")
    assert admin_group.status_code == 404

    removed = await scim.patch(
        f"/api/scim/v2/Groups/{group_id}",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "remove", "path": "members", "value": [{"value": scim_user_id}]}
            ],
        },
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["members"] == []
    assert store.list_policy_group_members(group_id) == []

    deactivated = await scim.delete(f"/api/scim/v2/Users/{scim_user_id}")
    assert deactivated.status_code == 204
    assert store.get_user(scim_user_id).is_active is False
    actions = {record.action for record in store.list_audit_logs()}
    assert {
        "scim.user.create",
        "scim.user.patch",
        "scim.user.update",
        "scim.user.deactivate",
        "scim.group.create",
        "scim.group.patch",
    }.issubset(actions)
    serialized_audit = json.dumps(
        [record.metadata for record in store.list_audit_logs()],
        sort_keys=True,
    )
    assert "scim-secret" not in serialized_audit
    assert admin_id

    await scim.aclose()
    await admin.aclose()
    await anonymous.aclose()


@pytest.mark.asyncio
async def test_scim_bearer_defaults_to_default_organization() -> None:
    store = InMemoryStore(Settings(scim_bearer_token="default-scim-secret"))
    app = create_app(
        store=store,
        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    scim = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"authorization": "Bearer default-scim-secret"},
    )

    created = await scim.post(
        "/api/scim/v2/Users",
        json={"userName": "default.scim@example.com"},
    )

    assert created.status_code == 201, created.text
    assert store.get_user(created.json()["id"]).organization_id == DEFAULT_ORGANIZATION_ID

    await scim.aclose()


@pytest.mark.asyncio
async def test_audit_export_and_metadata_redaction_block_adversarial_payloads() -> None:
    store = InMemoryStore()
    app = create_app(
        store=store,
        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    admin = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    admin_id = await _register_and_login(
        admin,
        store,
        email="audit-export-admin@example.com",
        username="audit-export-admin",
        role="admin",
    )
    jwt_like = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    secret_values = [
        "Bearer bearer-secret-token-1234567890",
        "gho_github_secret_token_1234567890",
        "sk-openai-secret-token-1234567890",
        jwt_like,
        "/root/workspace/llm-powered-log-analytic-p3/tests/fixtures/logs/auth.log",
    ]
    credential_values = ["password=hunter2", "api_key=abc123secret"]
    store.record_audit(
        action="adversarial.audit",
        user_id=admin_id,
        metadata={
            "safe": " ".join(secret_values),
            "credential_note": " ".join(credential_values),
            "note": "raw prompt classify this raw log payload",
            "prompt": "raw prompt should be removed",
            "raw_text": "raw log payload should be removed",
            "api_key": "abc123secret",
            "file_path": "/root/workspace/secret.log",
        },
    )
    case = store.create_case(
        user_id=admin_id,
        data={
            "title": "Redaction case",
            "issue_description": None,
            "product": "security",
            "service": "audit",
            "environment": "test",
            "incident_start": None,
            "incident_end": None,
            "timezone": "UTC",
        },
    )
    event = store.record_job_event(
        case_id=case.id,
        analysis_run_id="run-redaction",
        step_name="red_team",
        event_type="completed",
        status="completed",
        idempotency_key="red-team",
        metadata={
            "files": 1,
            "authorization": "Bearer event-secret",
            "prompt": "raw prompt",
            "input_path": "/root/workspace/raw.log",
            "safe_error": "failed with sk-event-secret-token-12345 at /tmp/raw.log",
        },
    )
    artifact = store.upsert_analysis_step_artifact(
        case_id=case.id,
        analysis_run_id="run-redaction",
        step_name="red_team",
        artifact_type="step_manifest",
        object_uri="memory://artifact",
        sha256="0" * 64,
        size_bytes=1,
        metadata={
            "artifact_error": "Bearer artifact-secret /var/log/auth.log",
            "prompt": "raw prompt",
            "raw_log": "raw log payload",
            "file_path": "/root/workspace/raw.log",
        },
    )

    serialized_event_metadata = json.dumps(event.metadata, sort_keys=True)
    serialized_artifact_metadata = json.dumps(artifact.metadata, sort_keys=True)
    for forbidden in secret_values:
        assert forbidden not in serialized_event_metadata
        assert forbidden not in serialized_artifact_metadata
    assert "prompt" not in serialized_event_metadata
    assert "raw_log" not in serialized_artifact_metadata
    assert "<REDACTED>" in serialized_artifact_metadata
    assert "<PATH>" in serialized_artifact_metadata

    for export_format in ("json", "ndjson", "csv"):
        exported = await admin.get(
            "/api/admin/audit-logs/export",
            params={"format": export_format, "action": "adversarial.audit"},
        )
        assert exported.status_code == 200, exported.text
        body = exported.text
        assert "adversarial.audit" in body
        for forbidden in secret_values:
            assert forbidden not in body
        for forbidden in credential_values:
            assert forbidden not in body
        assert "raw prompt classify this raw log payload" not in body
        assert "raw prompt should be removed" not in body
        assert "raw log payload should be removed" not in body
        assert "abc123secret" not in body
        assert "/root/workspace" not in body
        assert "<REDACTED>" in body
        assert "<PATH>" in body

    await admin.aclose()


@pytest.mark.asyncio
async def test_api_rate_limit_only_when_enabled() -> None:
    disabled_store = InMemoryStore(
        Settings(rate_limit_enabled=False, rate_limit_requests_per_minute=1)
    )
    disabled_app = create_app(
        store=disabled_store,        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    disabled_client = AsyncClient(
        transport=ASGITransport(app=disabled_app),
        base_url="http://testserver",
    )
    assert (await disabled_client.get("/api/cases")).status_code == 401
    assert (await disabled_client.get("/api/cases")).status_code == 401
    await disabled_client.aclose()

    enabled_store = InMemoryStore(
        Settings(rate_limit_enabled=True, rate_limit_requests_per_minute=2)
    )
    enabled_app = create_app(
        store=enabled_store,        model_gateway=MockAIPlatformAnnotationGateway(),
    )
    enabled_client = AsyncClient(
        transport=ASGITransport(app=enabled_app),
        base_url="http://testserver",
    )
    assert (await enabled_client.get("/api/cases")).status_code == 401
    assert (await enabled_client.get("/api/cases")).status_code == 401
    limited = await enabled_client.get("/api/cases")
    assert limited.status_code == 429
    assert "rate limit exceeded" in limited.json()["detail"]
    body = (await enabled_client.get("/metrics")).text
    assert 'logan_rate_limit_rejections_total{key_type="ip"}' in body
    assert "127.0.0.1" not in body
    assert "session:" not in body
    assert "logan_session" not in body
    assert "gho_secret_token_1234567890" not in body
    assert "password=hunter2" not in body
    await enabled_client.aclose()


@pytest.mark.asyncio
async def test_case_analysis_report_and_feedback_apis(tmp_path: Path) -> None:
    client, store, _ = await _authenticated_client(
        Settings(
            object_store_backend="local",
            local_object_store_dir=str(tmp_path / "object-store"),
            step_artifacts_enabled=True,
            step_artifact_failure_mode="fail",
        )
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
    analysis_result = store.get_analysis_result(case_id, run_id)
    assert analysis_result is not None
    model_invocations = store.list_audit_logs(case_id=case_id, action="model.invocation")
    assert len(model_invocations) == 1
    model_invocation_metadata = model_invocations[0].metadata
    assert model_invocation_metadata == {
        "analysis_run_id": run_id,
        "model_provider": "ai_platform",
        "model_name": status.json()["model_name"],
        "model_reasoning_effort": store.settings.ai_platform_reasoning_effort,
        "prompt_version": "annotation_v1",
        "representative_sample_count": len(analysis_result.samples),
        "model_input_count": len(analysis_result.model_inputs),
        "annotation_count": len(analysis_result.annotations),
        "template_count": len(analysis_result.templates),
        "redacted": True,
    }
    store.complete_analysis_run(
        run_id=run_id,
        result=analysis_result,
        user_id=store.users_by_username["engineer"],
    )
    assert len(store.list_audit_logs(case_id=case_id, action="model.invocation")) == 1
    serialized_model_invocation = json.dumps(model_invocation_metadata, sort_keys=True)
    for forbidden in (
        "raw_text",
        "raw_message",
        "model_inputs",
        '"prompt"',
        "representative_lines",
        "tests/fixtures",
        "auth.log",
        "payment.log",
        "gateway.log",
        "secret",
        "token",
    ):
        assert forbidden not in serialized_model_invocation
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
    assert completed_steps == ["materialize_inputs", *PIPELINE_STEPS]
    event_metadata = json.dumps([item["metadata"] for item in event_items], sort_keys=True)
    assert "model_inputs" not in event_metadata
    assert "representative_lines" not in event_metadata
    assert "timeout calling auth-service" not in event_metadata
    artifacts = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/artifacts")
    assert artifacts.status_code == 200, artifacts.text
    artifacts_body = artifacts.json()
    assert artifacts_body["total"] == len(PIPELINE_STEPS) + 1
    assert [item["step_name"] for item in artifacts_body["items"]] == [
        "materialize_inputs",
        *PIPELINE_STEPS,
    ]
    artifact_items = artifacts_body["items"]
    assert [item["step_name"] for item in artifact_items] == [
        "materialize_inputs",
        *PIPELINE_STEPS,
    ]
    assert {item["artifact_type"] for item in artifact_items} == {"step_manifest"}
    assert all(item["object_uri"] for item in artifact_items)
    assert all(len(item["sha256"]) == 64 for item in artifact_items)
    artifact_metadata = json.dumps(
        [item["metadata"] for item in artifact_items],
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
        assert forbidden not in artifact_metadata
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
    assert listed_run["model_provider"] == "ai_platform"
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
    original_causal_summary = causal_summary.json()
    assert "candidate" in original_causal_summary["summary_markdown"].lower()
    assert original_causal_summary["evidence_refs"]
    assert original_causal_summary["evidence_claims"]
    assert original_causal_summary["uncertainties"]
    assert original_causal_summary["details"]["source"] in {"llm", "fallback"}
    edited_summary = "# Edited Incident Diagnosis\n\nCandidate evidence has been reviewed."
    edited_customer_update = "Engineering has updated the customer-safe incident summary."
    patched_summary = await client.patch(
        f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary",
        json={
            "summary_markdown": edited_summary,
            "customer_update_markdown": edited_customer_update,
        },
    )
    assert patched_summary.status_code == 200, patched_summary.text
    patched_body = patched_summary.json()
    assert patched_body["summary_markdown"] == edited_summary
    assert patched_body["customer_update_markdown"] == edited_customer_update
    assert patched_body["edited"] is True
    assert patched_body["evidence_refs"] == original_causal_summary["evidence_refs"]
    assert patched_body["next_actions"] == original_causal_summary["next_actions"]
    assert patched_body["evidence_claims"] == original_causal_summary["evidence_claims"]
    assert patched_body["uncertainties"] == original_causal_summary["uncertainties"]
    assert patched_body["confidence"] == original_causal_summary["confidence"]
    fetched_patched_summary = await client.get(
        f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary"
    )
    assert fetched_patched_summary.json()["summary_markdown"] == edited_summary
    assert fetched_patched_summary.json()["edited"] is True
    result = store.get_analysis_result(case_id, run_id)
    assert result is not None
    assert result.causal_summary.summary_markdown == edited_summary
    assert result.causal_summary.edited is True
    assert result.exports["markdown"].content == edited_summary
    audit = store.list_audit_logs(case_id=case_id, action="causal_summary.edit")
    assert len(audit) == 1
    assert audit[0].target_type == "causal_summary"
    assert audit[0].target_id == run_id
    assert audit[0].metadata == {
        "analysis_run_id": run_id,
        "summary_length": len(edited_summary),
        "customer_update_length": len(edited_customer_update),
        "evidence_refs_count": len(original_causal_summary["evidence_refs"]),
        "edited": True,
    }

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
    assert tasks.json()["runtime_type"] == "ai_platform"
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_stream_fallback_without_context_does_not_call_gateway() -> None:
    gateway = MockAIPlatformAnnotationGateway()
    client, _, _ = await _authenticated_client(model_gateway=gateway)

    response = await client.post("/api/chat/stream", json={"message": "What happened?"})
    frames = _parse_sse_frames(response.text)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert frames == [
        ("delta", {"delta": "No case analysis context was found for this chat request."}),
        ("evidence", {"evidence_refs": []}),
        ("done", {"message": "No case analysis context was found for this chat request."}),
    ]
    assert gateway.calls == []
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_stream_uses_injected_streaming_gateway_with_context() -> None:
    gateway = StreamingChatGateway()
    client, _, _ = await _authenticated_client(model_gateway=gateway)
    case_id, run_id = await _create_completed_sample_run(client)
    gateway.calls.clear()

    response = await client.post(
        "/api/chat/stream",
        json={
            "message": "Why is auth-service ranked?",
            "case_id": case_id,
            "analysis_run_id": run_id,
        },
    )
    frames = _parse_sse_frames(response.text)

    assert response.status_code == 200, response.text
    assert [event for event, _payload in frames] == ["evidence", "delta", "delta", "done"]
    evidence = frames[0][1]["evidence_refs"]
    assert isinstance(evidence, list)
    assert 1 <= len(evidence) <= 5
    assert frames[1][1] == {"delta": "Auth-service "}
    assert frames[2][1] == {"delta": "is candidate evidence."}
    assert frames[3][1] == {"message": "Auth-service is candidate evidence."}

    assert len(gateway.calls) == 1
    call = gateway.calls[0]
    assert call["stream"] is True
    assert call["model"] == "gpt-5.4"
    assert call["reasoning_effort"] == "high"
    assert call["metadata"] == {
        "case_id": case_id,
        "analysis_run_id": run_id,
        "purpose": "case_chat",
    }
    context_text = call["input"][0]["content"][0]["text"]
    context = json.loads(context_text)
    assert context["user_message"] == "Why is auth-service ranked?"
    assert context["case_id"] == case_id
    assert context["analysis_run_id"] == run_id
    assert context["causal_summary"]
    assert 1 <= len(context["summary_rows"]) <= 5
    serialized_context = json.dumps(context, sort_keys=True)
    assert "raw_entries" not in serialized_context
    assert "raw_message" not in serialized_context
    assert "model_inputs" not in serialized_context
    assert "source_token" not in serialized_context
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_stream_gateway_error_frame_is_sanitized() -> None:
    client, _, _ = await _authenticated_client(model_gateway=StreamingErrorGateway())
    case_id, run_id = await _create_completed_sample_run(client)

    response = await client.post(
        "/api/chat/stream",
        json={
            "message": "Summarize the candidate cause.",
            "case_id": case_id,
            "analysis_run_id": run_id,
        },
    )
    frames = _parse_sse_frames(response.text)

    assert response.status_code == 200, response.text
    assert frames == [
        (
            "error",
            {
                "message": (
                    "stream failed source_token=<REDACTED> password=<REDACTED>"
                )
            },
        )
    ]
    assert "gho_secret_token_1234567890" not in response.text
    assert "hunter2" not in response.text
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
        step_name="ai_platform_annotation",
    )
    failed_events = [event for event in events if event.event_type == "failed"]
    assert len(failed_events) == 1
    failed_event = failed_events[0]
    assert failed_event.error_message
    assert "gho_secret_token_1234567890" not in failed_event.error_message
    assert "hunter2" not in failed_event.error_message
    assert failed_event.metadata == {}
    assert run.progress["steps"]["ai_platform_annotation"]["status"] == "failed"


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


@pytest.mark.asyncio
async def test_s3_upload_complete_uses_head_object_and_presigned_url() -> None:
    fake_s3 = FakeS3Client()
    client, store, _ = await _authenticated_client(
        Settings(
            object_store_backend="s3",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)
    content = b"2026-06-06T10:00:00Z ERROR gateway request failed\n"
    expected_sha = hashlib.sha256(content).hexdigest()

    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "../incident.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    assert upload.status_code == 200, upload.text
    payload = upload.json()
    file_id = payload["file_id"]
    assert payload["upload_backend"] == "s3"
    assert payload["upload_url"].startswith("https://minio.example/logan/")
    assert payload["upload_headers"] == {"content-type": "text/plain"}
    assert payload["object_uri"] is None

    upload_record = store.get_upload(file_id)
    assert upload_record is not None
    assert upload_record.object_uri == f"s3://logan/cases/{case_id}/uploads/{file_id}/incident.log"
    key = f"cases/{case_id}/uploads/{file_id}/incident.log"
    fake_s3.objects[("logan", key)] = {
        "ContentLength": len(content),
        "Metadata": {"sha256": expected_sha},
    }

    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={"sha256": expected_sha},
    )

    assert complete.status_code == 200, complete.text
    assert complete.json()["sha256"] == expected_sha
    assert fake_s3.head_calls == [{"Bucket": "logan", "Key": key}]
    completed = store.get_upload(file_id)
    assert completed is not None
    assert completed.completed is True
    assert completed.sha256 == expected_sha
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_multipart_upload_start_returns_plan_and_persists_metadata() -> None:
    fake_s3 = FakeS3Client()
    client, store, _ = await _authenticated_client(
        Settings(
            object_store_backend="minio",
            s3_endpoint="http://minio:9000",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
            s3_presign_expires_seconds=321,
            s3_multipart_threshold_bytes=10,
            s3_multipart_part_size_bytes=5,
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)

    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "../incident.log", "content_type": "text/plain", "size_bytes": 12},
    )

    assert upload.status_code == 200, upload.text
    payload = upload.json()
    file_id = payload["file_id"]
    assert payload["upload_backend"] == "minio"
    assert payload["upload_mode"] == "multipart"
    assert "object_uri" not in payload
    assert payload["multipart_upload_id"] == "multipart-1"
    assert payload["part_size_bytes"] == 5
    assert payload["part_count"] == 3
    assert payload["expires_in"] == 321
    assert [part["part_number"] for part in payload["parts"]] == [1, 2, 3]
    assert payload["parts"][0]["upload_headers"] == {}
    assert "partNumber=1" in payload["parts"][0]["upload_url"]

    key = f"cases/{case_id}/uploads/{file_id}/incident.log"
    assert fake_s3.create_multipart_calls == [
        {
            "Bucket": "logan",
            "Key": key,
            "ContentType": "text/plain",
            "UploadId": "multipart-1",
        }
    ]
    persisted = store.get_upload(file_id)
    assert persisted is not None
    assert persisted.upload_metadata == {
        "upload_mode": "multipart",
        "multipart_upload_id": "multipart-1",
        "part_size_bytes": 5,
        "part_count": 3,
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_multipart_upload_start_rejects_excessive_part_count() -> None:
    fake_s3 = FakeS3Client()
    client, _, _ = await _authenticated_client(
        Settings(
            object_store_backend="s3",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
            s3_multipart_threshold_bytes=1,
            s3_multipart_part_size_bytes=5,
            s3_multipart_max_parts=2,
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)

    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "incident.log", "content_type": "text/plain", "size_bytes": 11},
    )

    assert upload.status_code == 400
    assert "exceeding the maximum of 2" in upload.json()["detail"]
    assert fake_s3.create_multipart_calls == []
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_multipart_refresh_returns_fresh_urls_and_uploaded_parts() -> None:
    fake_s3 = FakeS3Client()
    client, store, _ = await _authenticated_client(
        Settings(
            object_store_backend="s3",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
            s3_multipart_threshold_bytes=10,
            s3_multipart_part_size_bytes=5,
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)
    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "incident.log", "content_type": "text/plain", "size_bytes": 12},
    )
    assert upload.status_code == 200, upload.text
    started = upload.json()
    file_id = started["file_id"]
    initial_url = started["parts"][0]["upload_url"]
    persisted = store.get_upload(file_id)
    assert persisted is not None
    upload_id = persisted.upload_metadata["multipart_upload_id"]
    key = f"cases/{case_id}/uploads/{file_id}/incident.log"
    fake_s3.uploaded_parts[("logan", key, upload_id)] = [
        {"PartNumber": 1, "ETag": '"etag-1"', "Size": 5}
    ]

    refreshed = await client.get(f"/api/cases/{case_id}/uploads/{file_id}/multipart")

    assert refreshed.status_code == 200, refreshed.text
    payload = refreshed.json()
    assert payload["upload_mode"] == "multipart"
    assert payload["multipart_upload_id"] == upload_id
    assert len(payload["parts"]) == 3
    assert payload["parts"][0]["upload_url"] != initial_url
    assert payload["uploaded_parts"] == [
        {"part_number": 1, "etag": '"etag-1"', "size_bytes": 5}
    ]
    assert fake_s3.list_parts_calls == [
        {"Bucket": "logan", "Key": key, "UploadId": upload_id}
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_multipart_complete_finishes_s3_upload_and_marks_complete() -> None:
    fake_s3 = FakeS3Client()
    client, store, _ = await _authenticated_client(
        Settings(
            object_store_backend="s3",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
            s3_multipart_threshold_bytes=10,
            s3_multipart_part_size_bytes=5,
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)
    content = b"hello world!"
    expected_sha = hashlib.sha256(content).hexdigest()
    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "incident.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    assert upload.status_code == 200, upload.text
    file_id = upload.json()["file_id"]
    persisted = store.get_upload(file_id)
    assert persisted is not None
    upload_id = persisted.upload_metadata["multipart_upload_id"]
    key = f"cases/{case_id}/uploads/{file_id}/incident.log"
    fake_s3.complete_objects[("logan", key, upload_id)] = {
        "ContentLength": len(content),
        "Metadata": {},
    }

    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={
            "sha256": expected_sha,
            "multipart_upload_id": upload_id,
            "parts": [
                {"part_number": 3, "etag": '"etag-3"'},
                {"part_number": 1, "etag": '"etag-1"'},
                {"part_number": 2, "etag": '"etag-2"'},
            ],
        },
    )

    assert complete.status_code == 200, complete.text
    assert complete.json()["sha256"] == expected_sha
    assert fake_s3.complete_multipart_calls == [
        {
            "Bucket": "logan",
            "Key": key,
            "UploadId": upload_id,
            "MultipartUpload": {
                "Parts": [
                    {"PartNumber": 1, "ETag": '"etag-1"'},
                    {"PartNumber": 2, "ETag": '"etag-2"'},
                    {"PartNumber": 3, "ETag": '"etag-3"'},
                ]
            },
        }
    ]
    assert fake_s3.head_calls == [{"Bucket": "logan", "Key": key}]
    completed = store.get_upload(file_id)
    assert completed is not None
    assert completed.completed is True
    assert completed.sha256 == expected_sha
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_multipart_abort_marks_metadata_and_is_idempotent() -> None:
    fake_s3 = FakeS3Client()
    client, store, _ = await _authenticated_client(
        Settings(
            object_store_backend="minio",
            s3_endpoint="http://minio:9000",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
            s3_multipart_threshold_bytes=10,
            s3_multipart_part_size_bytes=5,
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)
    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "incident.log", "content_type": "text/plain", "size_bytes": 12},
    )
    assert upload.status_code == 200, upload.text
    file_id = upload.json()["file_id"]
    persisted = store.get_upload(file_id)
    assert persisted is not None
    upload_id = persisted.upload_metadata["multipart_upload_id"]
    key = f"cases/{case_id}/uploads/{file_id}/incident.log"

    aborted = await client.delete(f"/api/cases/{case_id}/uploads/{file_id}/multipart")
    second_abort = await client.delete(f"/api/cases/{case_id}/uploads/{file_id}/multipart")

    assert aborted.status_code == 200, aborted.text
    assert second_abort.status_code == 200, second_abort.text
    assert aborted.json()["status"] == "aborted"
    assert fake_s3.abort_multipart_calls == [
        {"Bucket": "logan", "Key": key, "UploadId": upload_id}
    ]
    updated = store.get_upload(file_id)
    assert updated is not None
    assert updated.upload_metadata["aborted_at"]
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_upload_complete_rejects_missing_object_or_size_mismatch() -> None:
    fake_s3 = FakeS3Client()
    client, _, _ = await _authenticated_client(
        Settings(
            object_store_backend="minio",
            s3_endpoint="http://minio:9000",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)
    content = b"gateway failed\n"
    expected_sha = hashlib.sha256(content).hexdigest()

    missing_upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "missing.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    missing_file_id = missing_upload.json()["file_id"]
    missing = await client.post(
        f"/api/cases/{case_id}/uploads/{missing_file_id}/complete",
        json={"sha256": expected_sha},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"] == "upload content has not been uploaded"

    mismatch_upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "mismatch.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    mismatch_file_id = mismatch_upload.json()["file_id"]
    fake_s3.objects[("logan", f"cases/{case_id}/uploads/{mismatch_file_id}/mismatch.log")] = {
        "ContentLength": len(content) + 1,
        "Metadata": {},
    }
    mismatch = await client.post(
        f"/api/cases/{case_id}/uploads/{mismatch_file_id}/complete",
        json={"sha256": expected_sha},
    )
    assert mismatch.status_code == 400
    assert "upload size mismatch" in mismatch.json()["detail"]

    sha_upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "sha.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    sha_file_id = sha_upload.json()["file_id"]
    fake_s3.objects[("logan", f"cases/{case_id}/uploads/{sha_file_id}/sha.log")] = {
        "ContentLength": len(content),
        "Metadata": {"sha256": "0" * 64},
    }
    sha_mismatch = await client.post(
        f"/api/cases/{case_id}/uploads/{sha_file_id}/complete",
        json={"sha256": expected_sha},
    )
    assert sha_mismatch.status_code == 409
    assert sha_mismatch.json()["detail"] == "upload sha256 does not match stored content metadata"
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_input_file_ids_analysis_materializes_completed_upload() -> None:
    fake_s3 = FakeS3Client()
    app_settings = Settings(
        object_store_backend="s3",
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    client, store, _ = await _authenticated_client(
        app_settings,
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)
    content = (
        b"2026-06-06T10:00:00Z ERROR gateway-service failed checkout request\n"
    )
    expected_sha = hashlib.sha256(content).hexdigest()
    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "gateway.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    file_id = upload.json()["file_id"]
    key = f"cases/{case_id}/uploads/{file_id}/gateway.log"
    fake_s3.objects[("logan", key)] = {
        "ContentLength": len(content),
        "Metadata": {},
        "Body": content,
    }
    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={"sha256": expected_sha},
    )
    assert complete.status_code == 200, complete.text

    run = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={"input_file_ids": [file_id], "config": {"default_window_size_seconds": 60}},
    )

    assert run.status_code == 200, run.text
    run_id = run.json()["analysis_run_id"]
    status = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "completed"
    assert status.json()["progress"]["files_processed"] == 1
    logs = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/logs")
    assert logs.status_code == 200, logs.text
    assert [item["file_path"] for item in logs.json()["items"]] == ["gateway.log"]
    summary = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/summary")
    assert summary.status_code == 200, summary.text
    assert fake_s3.download_calls
    downloaded_path = Path(fake_s3.download_calls[0]["Filename"])
    assert not downloaded_path.exists()
    materialize_events = store.list_job_events(
        analysis_run_id=run_id,
        step_name="materialize_inputs",
    )
    assert [event.metadata for event in materialize_events] == [
        {
            "source_count": 1,
            "materialized_count": 1,
            "storage_backend_counts": {"s3": 1},
        }
    ]
    serialized_metadata = json.dumps(materialize_events[0].metadata, sort_keys=True)
    assert key not in serialized_metadata
    assert "secret" not in serialized_metadata.lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_s3_temporal_input_file_ids_pass_object_uri_to_workflow(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_start_analyze_case_workflow(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "logan_workers.temporal_client.start_analyze_case_workflow",
        fake_start_analyze_case_workflow,
    )
    fake_s3 = FakeS3Client()
    client, store, _ = await _authenticated_client(
        Settings(
            analysis_orchestrator="temporal",
            object_store_backend="s3",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
            database_url="postgresql+psycopg://logan:secret@postgres/logan",
        ),
        s3_client_factory=lambda _: fake_s3,
    )
    case_id = await _create_case(client)
    content = b"gateway failed\n"
    expected_sha = hashlib.sha256(content).hexdigest()
    upload = await client.post(
        f"/api/cases/{case_id}/uploads",
        json={"filename": "gateway.log", "content_type": "text/plain", "size_bytes": len(content)},
    )
    file_id = upload.json()["file_id"]
    fake_s3.objects[("logan", f"cases/{case_id}/uploads/{file_id}/gateway.log")] = {
        "ContentLength": len(content),
        "Metadata": {},
        "Body": content,
    }
    complete = await client.post(
        f"/api/cases/{case_id}/uploads/{file_id}/complete",
        json={"sha256": expected_sha},
    )
    assert complete.status_code == 200, complete.text

    run = await client.post(
        f"/api/cases/{case_id}/analysis-runs",
        json={"input_file_ids": [file_id], "config": {"default_window_size_seconds": 60}},
    )

    assert run.status_code == 200, run.text
    persisted_run = store.get_analysis_run(run.json()["analysis_run_id"])
    assert persisted_run is not None
    assert persisted_run.status == "processing"
    assert captured["paths"] == [f"s3://logan/cases/{case_id}/uploads/{file_id}/gateway.log"]
    assert fake_s3.download_calls == []
    await client.aclose()
