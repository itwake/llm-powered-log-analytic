from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from app.config import Settings
from app.services import analysis_artifacts
from app.services.analysis_artifacts import write_step_manifest
from app.services.analysis_inputs import materialize_analysis_inputs
from app.services.object_store import (
    digest_bytes,
    file_uri_to_path,
    local_upload_object_uri,
    path_to_file_uri,
    safe_filename,
    write_bytes,
)
from app.store import JobEventRecord


def test_safe_filename_removes_paths_and_control_characters() -> None:
    assert safe_filename("../evil.log") == "evil.log"
    assert safe_filename("..\\evil.log") == "evil.log"
    assert safe_filename("evil\x00.log") == "evil.log"
    assert safe_filename(".") == "upload.bin"
    assert safe_filename("") == "upload.bin"
    assert safe_filename(None) == "upload.bin"


def test_file_uri_round_trip_uses_forward_slashes(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "incident.log"

    uri = path_to_file_uri(path)

    assert uri.startswith("file://")
    assert uri.endswith("/incident.log")
    assert "\\" not in uri
    assert file_uri_to_path(uri) == path.resolve()
    if os.name != "nt":
        assert uri.startswith("file:///")


def test_file_uri_to_path_rejects_non_file_uri() -> None:
    with pytest.raises(ValueError, match="not file-backed"):
        file_uri_to_path("https://example.com/log.txt")


def test_local_upload_uri_is_scoped_and_sanitized(tmp_path: Path) -> None:
    app_settings = Settings(local_object_store_dir=str(tmp_path / "objects"))

    uri = local_upload_object_uri(
        case_id="../case-1",
        file_id="..\\file-1",
        filename="../../incident?.log",
        app_settings=app_settings,
    )

    path = file_uri_to_path(uri)
    assert (
        path
        == (
            tmp_path / "objects" / "cases" / "case-1" / "uploads" / "file-1" / "incident_.log"
        ).resolve()
    )


def test_write_object_persists_content_and_digest(tmp_path: Path) -> None:
    content = b"2026-06-06T10:00:00Z ERROR gateway failed\n"
    uri = path_to_file_uri(tmp_path / "objects" / "incident.log")

    written = write_bytes(uri, content)

    assert file_uri_to_path(uri).read_bytes() == content
    assert written.sha256 == digest_bytes(content)[0]
    assert written.size_bytes == len(content)


def test_materialize_analysis_inputs_normalizes_file_uri(tmp_path: Path) -> None:
    plain_path = tmp_path / "plain.log"
    file_uri_path = tmp_path / "file-uri.log"
    plain_path.write_text("plain\n", encoding="utf-8")
    file_uri_path.write_text("file-uri\n", encoding="utf-8")
    inputs = [str(plain_path), path_to_file_uri(file_uri_path)]

    with materialize_analysis_inputs(inputs) as paths:
        assert paths == [str(plain_path), str(file_uri_path.resolve())]


def test_step_manifest_writer_uses_local_object_path_and_safe_json(
    tmp_path: Path,
) -> None:
    app_settings = Settings(local_object_store_dir=str(tmp_path / "object-store"))
    event = JobEventRecord(
        id="event-1",
        case_id="case-" + "1" * 64,
        analysis_run_id="run-" + "2" * 64,
        step_name="ai_platform_annotation",
        event_type="completed",
        status="completed",
        attempt=1,
        idempotency_key="ai_platform_annotation:attempt:1",
        metadata={
            "annotations": 3,
            "raw_text": "raw secret log line",
            "prompt": "model prompt",
            "token": "gho_secret_token",
            "file_path": "/customer/acme/payment.log",
            "export_types": ["html", "json"],
        },
    )

    written = write_step_manifest(event=event, app_settings=app_settings)
    artifact_path = file_uri_to_path(written.object_uri)
    manifest = json.loads(artifact_path.read_bytes())

    assert artifact_path.parent.name == "step-artifacts"
    assert artifact_path.name.endswith(".json")
    assert len(str(artifact_path)) < len(str(tmp_path / "object-store")) + 100
    assert written.sha256 == hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert manifest["completed_event"]["metadata"] == {
        "annotations": 3,
        "export_types": ["html", "json"],
    }
    serialized = json.dumps(manifest, sort_keys=True).lower()
    for forbidden in (
        "raw secret log line",
        "model prompt",
        "gho_secret_token",
        "/customer/acme/payment.log",
        "raw_text",
        "prompt",
        "token",
        "file_path",
    ):
        assert forbidden not in serialized


def test_step_artifact_error_sanitizer_removes_paths_and_tokens() -> None:
    app_settings = Settings(local_object_store_dir="/tmp/customer/acme/object-store")
    message = analysis_artifacts._sanitize_artifact_error(
        OSError(
            "failed writing /tmp/customer/acme/object-store/cases/case-1/steps/x.json "
            "token=gho_secret_token_1234567890"
        ),
        app_settings,
    )

    assert "/tmp/customer" not in message
    assert "gho_secret_token_1234567890" not in message
    assert "<PATH>" in message or "<LOCAL_OBJECT_STORE>" in message
