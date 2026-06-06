from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, settings
from app.services.object_store import (
    ObjectStoreConfigurationError,
    digest_bytes,
    file_uri_to_path,
    get_s3_client,
    is_local_backend,
    is_s3_backend,
    path_to_file_uri,
    s3_object_uri,
    write_bytes,
)
from app.store import (
    JobEventRecord,
    MetadataStore,
    sanitize_artifact_metadata,
    sanitize_error_message,
)


STEP_MANIFEST_ARTIFACT_TYPE = "step_manifest"
STEP_MANIFEST_CONTENT_TYPE = "application/json"
_POSIX_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s'\",;:]+/)+[^\s'\",;:]+")
_WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:\\[^\s'\",;]+")


@dataclass(frozen=True)
class StepArtifactWriteResult:
    artifact_type: str
    object_uri: str
    sha256: str
    size_bytes: int
    metadata: dict[str, Any]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_object_segment(value: str | None, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.=-]+", "_", text)
    text = text.strip("._-")
    return text[:128] or fallback


def _step_artifact_key(*, case_id: str, analysis_run_id: str, step_name: str) -> str:
    return "/".join(
        [
            "cases",
            _safe_object_segment(case_id, "case"),
            "analysis-runs",
            _safe_object_segment(analysis_run_id, "run"),
            "steps",
            f"{_safe_object_segment(step_name, 'step')}.json",
        ]
    )


def step_artifact_object_uri(
    *,
    case_id: str,
    analysis_run_id: str,
    step_name: str,
    app_settings: Settings = settings,
) -> str:
    key = _step_artifact_key(
        case_id=case_id,
        analysis_run_id=analysis_run_id,
        step_name=step_name,
    )
    if is_local_backend(app_settings):
        path = Path(app_settings.local_object_store_dir) / key
        return path_to_file_uri(path)
    if is_s3_backend(app_settings):
        if not app_settings.s3_bucket:
            raise ObjectStoreConfigurationError(
                "LOGAN_S3_BUCKET is required for step artifact storage"
            )
        return s3_object_uri(bucket=app_settings.s3_bucket, key=key)
    raise ObjectStoreConfigurationError(
        "LOGAN_OBJECT_STORE_BACKEND must be local, s3, or minio for step artifacts"
    )


def _event_idempotency_hash(event: JobEventRecord) -> str:
    return hashlib.sha256(event.idempotency_key.encode("utf-8")).hexdigest()


def build_step_manifest(
    *,
    event: JobEventRecord,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or _now_iso()
    return {
        "case_id": event.case_id,
        "analysis_run_id": event.analysis_run_id,
        "step_name": event.step_name,
        "artifact_type": STEP_MANIFEST_ARTIFACT_TYPE,
        "manifest_version": 1,
        "completed_event": {
            "event_type": event.event_type,
            "status": event.status,
            "attempt": event.attempt,
            "idempotency_key_hash": _event_idempotency_hash(event),
            "metadata": sanitize_artifact_metadata(event.metadata),
            "created_at": event.created_at.isoformat(),
        },
        "created_at": created,
    }


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _write_s3_step_manifest(
    *,
    object_uri: str,
    content: bytes,
    sha256: str,
    app_settings: Settings,
    s3_client_factory: Any | None = None,
) -> None:
    if not object_uri.startswith("s3://"):
        raise ValueError("step artifact object URI is not S3-backed")
    bucket, _, key = object_uri.removeprefix("s3://").partition("/")
    if not bucket or not key:
        raise ValueError("invalid S3 step artifact object URI")
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType=STEP_MANIFEST_CONTENT_TYPE,
        Metadata={
            "sha256": sha256,
            "content-type": STEP_MANIFEST_CONTENT_TYPE,
        },
    )


def write_step_manifest(
    *,
    event: JobEventRecord,
    app_settings: Settings = settings,
    s3_client_factory: Any | None = None,
) -> StepArtifactWriteResult:
    manifest = build_step_manifest(event=event)
    content = _manifest_bytes(manifest)
    sha256, size_bytes = digest_bytes(content)
    object_uri = step_artifact_object_uri(
        case_id=event.case_id,
        analysis_run_id=event.analysis_run_id,
        step_name=event.step_name,
        app_settings=app_settings,
    )
    if object_uri.startswith("s3://"):
        _write_s3_step_manifest(
            object_uri=object_uri,
            content=content,
            sha256=sha256,
            app_settings=app_settings,
            s3_client_factory=s3_client_factory,
        )
    else:
        stored = write_bytes(object_uri, content)
        object_uri = stored.object_uri
        sha256 = stored.sha256 or sha256
        size_bytes = stored.size_bytes

    return StepArtifactWriteResult(
        artifact_type=STEP_MANIFEST_ARTIFACT_TYPE,
        object_uri=object_uri,
        sha256=sha256,
        size_bytes=size_bytes,
        metadata={
            "manifest_version": 1,
            "event_type": event.event_type,
            "status": event.status,
            "attempt": event.attempt,
            "idempotency_key_hash": _event_idempotency_hash(event),
            "storage_backend": "s3" if object_uri.startswith("s3://") else "local",
            "content_type": STEP_MANIFEST_CONTENT_TYPE,
        },
    )


def _failure_mode(app_settings: Settings) -> str:
    mode = (app_settings.step_artifact_failure_mode or "warn").lower()
    return mode if mode in {"warn", "fail"} else "warn"


def _sanitize_artifact_error(error: Exception, app_settings: Settings) -> str:
    message = sanitize_error_message(error)
    for path_text in {
        str(Path(app_settings.local_object_store_dir)),
        str(Path(app_settings.local_object_store_dir).resolve()),
    }:
        if path_text:
            message = message.replace(path_text, "<LOCAL_OBJECT_STORE>")
    message = _POSIX_PATH_PATTERN.sub("<PATH>", message)
    message = _WINDOWS_PATH_PATTERN.sub("<PATH>", message)
    return message


def materialize_step_artifact_for_event(
    *,
    store: MetadataStore,
    event: JobEventRecord,
    app_settings: Settings = settings,
    s3_client_factory: Any | None = None,
) -> None:
    if not app_settings.step_artifacts_enabled:
        return
    if event.event_type != "completed":
        return
    try:
        written = write_step_manifest(
            event=event,
            app_settings=app_settings,
            s3_client_factory=s3_client_factory,
        )
        store.upsert_analysis_step_artifact(
            case_id=event.case_id,
            analysis_run_id=event.analysis_run_id,
            step_name=event.step_name,
            artifact_type=written.artifact_type,
            object_uri=written.object_uri,
            sha256=written.sha256,
            size_bytes=written.size_bytes,
            metadata=written.metadata,
        )
    except Exception as exc:
        sanitized_error = _sanitize_artifact_error(exc, app_settings)
        if _failure_mode(app_settings) == "fail":
            raise RuntimeError(sanitized_error) from exc
        store.record_audit(
            action="analysis_step_artifact.materialize_failed",
            target_type="analysis_run",
            target_id=event.analysis_run_id,
            case_id=event.case_id,
            metadata={
                "analysis_run_id": event.analysis_run_id,
                "artifact_error": sanitized_error,
                "artifact_type": STEP_MANIFEST_ARTIFACT_TYPE,
                "step_name": event.step_name,
            },
        )


def best_effort_delete_step_artifact_object(
    object_uri: str,
    *,
    app_settings: Settings = settings,
) -> None:
    if not object_uri.startswith("file://"):
        return
    try:
        path = file_uri_to_path(object_uri)
        root = Path(app_settings.local_object_store_dir).resolve()
        resolved_path = path.resolve()
        if root not in resolved_path.parents and resolved_path != root:
            return
        resolved_path.unlink(missing_ok=True)
    except Exception:
        return
