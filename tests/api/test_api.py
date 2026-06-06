from __future__ import annotations

import hashlib
import io
import json
from collections.abc import AsyncIterator
from pathlib import Path
import zipfile

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from logan_workers.activities.inference import MockCopilotAnnotationGateway

from app.config import Settings
from app.core.security import decrypt_token
from app.main import create_app
from app.services.copilot_model_gateway import (
    CopilotCredentialError,
    CopilotModelGateway,
    CopilotTransportError,
)
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


class StreamingChatGateway(MockCopilotAnnotationGateway):
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


class StreamingErrorGateway(MockCopilotAnnotationGateway):
    async def responses(self, **kwargs):
        if kwargs.get("stream"):
            raise CopilotTransportError(
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
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=model_gateway or MockCopilotAnnotationGateway(),
        s3_client_factory=s3_client_factory,
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


async def _register_and_login(
    client: AsyncClient,
    store: InMemoryStore,
    *,
    email: str,
    username: str,
    full_name: str | None = None,
    role: str = "engineer",
) -> str:
    register = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": username,
            "full_name": full_name,
            "password": "password123",
        },
    )
    assert register.status_code == 200, register.text
    user_id = store.users_by_username[username]
    store.users[user_id].role = role
    login = await client.post(
        "/api/auth/login",
        json={"email_or_username": username, "password": "password123"},
    )
    assert login.status_code == 200, login.text
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
    assert upload.json()["upload_url"].startswith("http://testserver/api/cases/")
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
async def test_prometheus_metrics_endpoint_records_safe_api_request_metrics() -> None:
    store = InMemoryStore(Settings(metrics_enabled=True))
    app = create_app(
        store=store,
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
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
            github_copilot_token="copilot_secret_1234567890",
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
    disconnect = await client.delete("/api/copilot/auth/credential")
    assert disconnect.status_code == 200, disconnect.text
    assert disconnect.json() == {"status": "disconnected", "revoked_count": 1}
    assert "token" not in disconnect.text
    assert "encrypted_token" not in disconnect.text
    me_disconnected = await client.get("/api/auth/me")
    assert me_disconnected.json()["user"]["has_copilot_credential"] is False
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
    user_id = store.users_by_username["no-token"]
    plugin_token = "copilot_api_response_secret_token"
    store.save_credential(
        user_id=user_id,
        credential_type="copilot_plugin_token",
        token=plugin_token,
        github_base_url="https://github.com",
    )
    disconnect = await client.delete("/api/copilot/auth/credential")

    assert checked.json()["status"] == "authorized"
    assert disconnect.json() == {"status": "disconnected", "revoked_count": 2}
    for response in (started, checked, me, disconnect):
        assert source_token not in response.text
        assert plugin_token not in response.text
        assert "encrypted_token" not in response.text
        assert "token_hint" not in response.text
    audit = store.list_audit_logs(action="copilot.disconnect")[0]
    serialized_audit_metadata = json.dumps(audit.metadata, sort_keys=True)
    assert source_token not in serialized_audit_metadata
    assert plugin_token not in serialized_audit_metadata
    assert "token_hint" not in serialized_audit_metadata
    await client.aclose()


@pytest.mark.asyncio
async def test_case_rbac_collaborator_roles_are_enforced(tmp_path: Path) -> None:
    store = InMemoryStore(Settings(local_object_store_dir=str(tmp_path / "object-store")))
    app = create_app(
        store=store,
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
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
async def test_admin_api_settings_are_safe_and_admin_only() -> None:
    store = InMemoryStore(
        Settings(
            database_url="postgresql://logan:db-secret@postgres/logan",
            github_source_token="gho_source_secret",
            github_copilot_token="copilot-secret",
            s3_access_key="access-secret",
            s3_secret_key="s3-secret",
            clickhouse_password="clickhouse-secret",
            opensearch_password="opensearch-secret",
            rate_limit_enabled=False,
        )
    )
    app = create_app(
        store=store,
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
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
        "copilot-secret",
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
async def test_api_rate_limit_only_when_enabled() -> None:
    disabled_store = InMemoryStore(
        Settings(rate_limit_enabled=False, rate_limit_requests_per_minute=1)
    )
    disabled_app = create_app(
        store=disabled_store,
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
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
        store=enabled_store,
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
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
async def test_disconnect_revokes_credentials_for_gateway_use() -> None:
    source_token = "gho_disconnect_source_token"
    store = InMemoryStore(Settings(github_copilot_token=None, github_source_token=None))
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
            "email": "disconnect@example.com",
            "username": "disconnect",
            "full_name": "Disconnect",
            "password": "password123",
        },
    )
    await client.post(
        "/api/auth/login",
        json={"email_or_username": "disconnect", "password": "password123"},
    )
    user_id = store.users_by_username["disconnect"]
    started = await client.post("/api/copilot/auth/start", json={"github_base_url": "https://github.com"})
    authorized = await client.post(
        "/api/copilot/auth/check", json={"auth_id": started.json()["auth_id"]}
    )
    assert authorized.json()["status"] == "authorized"
    credential = store.get_credential(user_id=user_id, credential_type="github_source_oauth")
    assert credential is not None
    assert (
        decrypt_token(credential.encrypted_token, store.settings.credential_encryption_key)
        == source_token
    )

    disconnect = await client.delete("/api/copilot/auth/credential")
    assert disconnect.json() == {"status": "disconnected", "revoked_count": 1}
    assert store.get_credential(user_id=user_id, credential_type="github_source_oauth") is None

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"revoked credential should not make {request.method} request")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = CopilotModelGateway(
        store=store,
        app_settings=store.settings,
        http_client=http_client,
    )
    with pytest.raises(CopilotCredentialError):
        await gateway.responses(user_id=user_id, model="gpt-5.4", instructions=None, input=[])
    await http_client.aclose()
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
    artifacts = await client.get(f"/api/cases/{case_id}/analysis-runs/{run_id}/artifacts")
    assert artifacts.status_code == 200, artifacts.text
    artifacts_body = artifacts.json()
    assert artifacts_body["total"] == len(PIPELINE_STEPS)
    artifact_items = artifacts_body["items"]
    assert [item["step_name"] for item in artifact_items] == PIPELINE_STEPS
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
async def test_chat_stream_fallback_without_context_does_not_call_gateway() -> None:
    gateway = MockCopilotAnnotationGateway()
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
async def test_s3_input_file_ids_analysis_returns_clear_non_file_backed_error() -> None:
    fake_s3 = FakeS3Client()
    client, _, _ = await _authenticated_client(
        Settings(
            object_store_backend="s3",
            s3_bucket="logan",
            s3_access_key="access",
            s3_secret_key="secret",
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

    assert run.status_code == 400
    assert run.json()["detail"] == f"upload {file_id} is not file-backed and cannot be analyzed locally"
    await client.aclose()
