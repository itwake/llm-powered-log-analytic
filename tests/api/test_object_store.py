from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from app.config import Settings
from app.services import analysis_artifacts
from app.services.analysis_artifacts import write_step_manifest
from app.services.analysis_inputs import materialize_analysis_inputs
from app.services.object_store import (
    ObjectStoreError,
    create_multipart_upload_plan,
    create_presigned_upload,
    file_uri_to_path,
    parse_s3_object_uri,
    path_to_file_uri,
    s3_upload_key,
    s3_upload_object_uri,
    safe_filename,
)
from app.store import JobEventRecord


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.download_calls: list[dict[str, str]] = []
        self.get_object_calls: list[dict[str, str]] = []
        self.presign_calls: list[dict[str, object]] = []
        self.put_object_calls: list[dict[str, object]] = []

    def generate_presigned_url(self, operation: str, **kwargs: object) -> str:
        self.presign_calls.append({"operation": operation, **kwargs})
        return "https://minio.example/logan/upload?signature=fake"

    def put_object(self, **kwargs: object) -> dict[str, object]:
        self.put_object_calls.append(dict(kwargs))
        return {"ETag": '"fake-etag"'}

    def download_file(self, *, Bucket: str, Key: str, Filename: str) -> None:
        self.download_calls.append({"Bucket": Bucket, "Key": Key, "Filename": Filename})
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.get_object_calls.append({"Bucket": Bucket, "Key": Key})
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


class GetObjectOnlyFakeS3Client:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.get_object_calls: list[dict[str, str]] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.get_object_calls.append({"Bucket": Bucket, "Key": Key})
        return {"Body": io.BytesIO(self.content)}


def test_safe_filename_sanitizes_posix_and_windows_path_separators() -> None:
    assert safe_filename("../evil.log") == "evil.log"
    assert safe_filename("..\\evil.log") == "evil.log"


def test_safe_filename_falls_back_for_empty_or_directory_sentinels() -> None:
    assert safe_filename(".") == "upload.bin"
    assert safe_filename("..") == "upload.bin"
    assert safe_filename("") == "upload.bin"
    assert safe_filename(None) == "upload.bin"


def test_safe_filename_strips_control_characters() -> None:
    assert safe_filename("evil\x00.log") == "evil.log"
    assert safe_filename("\x00") == "upload.bin"


def test_path_to_file_uri_uses_forward_slash_separators(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "incident.log"

    uri = path_to_file_uri(path)

    assert uri.startswith("file://")
    assert uri.endswith("/incident.log")
    assert "\\" not in uri
    if os.name != "nt":
        assert uri.startswith("file:///")


def test_file_uri_to_path_accepts_normalized_file_uri_shapes() -> None:
    assert file_uri_to_path("file://C:/tmp/x.log") == Path("C:/tmp/x.log")
    if os.name == "nt":
        assert file_uri_to_path("file:///C:/tmp/x.log") == Path("C:/tmp/x.log")
        assert file_uri_to_path("file://C:\\tmp\\x.log") == Path("C:\\tmp\\x.log")
    else:
        assert file_uri_to_path("file:///tmp/x.log") == Path("/tmp/x.log")


def test_s3_upload_key_uses_safe_filename_and_relative_segments() -> None:
    key = s3_upload_key(
        case_id="../case-1",
        file_id="..\\file-1",
        filename="../../incident?.log",
    )

    assert key == "cases/case-1/uploads/file-1/incident?.log"
    assert "/../" not in key
    assert "\\" not in key


def test_s3_upload_object_uri_round_trips_bucket_and_key() -> None:
    app_settings = Settings(
        object_store_backend="s3",
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )

    object_uri = s3_upload_object_uri(
        case_id="case-1",
        file_id="file-1",
        filename="incident #1.log",
        app_settings=app_settings,
    )

    assert object_uri == "s3://logan/cases/case-1/uploads/file-1/incident%20%231.log"
    assert parse_s3_object_uri(object_uri) == (
        "logan",
        "cases/case-1/uploads/file-1/incident #1.log",
    )


def test_materialize_analysis_inputs_preserves_path_and_file_uri(tmp_path: Path) -> None:
    plain_path = tmp_path / "plain.log"
    file_uri_path = tmp_path / "file-uri.log"
    plain_path.write_text("plain\n", encoding="utf-8")
    file_uri_path.write_text("file-uri\n", encoding="utf-8")
    app_settings = Settings(analysis_input_tmp_dir=str(tmp_path / "analysis-inputs"))

    with materialize_analysis_inputs(
        [str(plain_path), path_to_file_uri(file_uri_path)],
        app_settings,
        run_id="run-1",
    ) as paths:
        assert paths == [str(plain_path), str(file_uri_path)]


def test_materialize_analysis_inputs_downloads_s3_and_cleans_temp_dir(
    tmp_path: Path,
) -> None:
    app_settings = Settings(
        object_store_backend="minio",
        analysis_input_tmp_dir=str(tmp_path / "analysis-inputs"),
        s3_endpoint="http://minio:9000",
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    fake_client = FakeS3Client()
    key = "cases/case-1/uploads/file-1/incident.log"
    fake_client.objects[("logan", key)] = b"2026-06-06T10:00:00Z ERROR gateway failed\n"
    materialized_path: Path | None = None

    with materialize_analysis_inputs(
        [f"s3://logan/{key}"],
        app_settings,
        run_id="run-1",
        s3_client_factory=lambda _: fake_client,
    ) as paths:
        assert len(paths) == 1
        materialized_path = Path(paths[0])
        assert materialized_path.read_bytes() == fake_client.objects[("logan", key)]
        assert materialized_path.name == "incident.log"
        assert materialized_path.parent.parent.parent == Path(
            app_settings.analysis_input_tmp_dir
        )

    assert materialized_path is not None
    assert not materialized_path.exists()
    assert fake_client.download_calls == [
        {
            "Bucket": "logan",
            "Key": key,
            "Filename": str(materialized_path),
        }
    ]


def test_materialize_analysis_inputs_supports_get_object_body_fakes(
    tmp_path: Path,
) -> None:
    app_settings = Settings(
        object_store_backend="s3",
        analysis_input_tmp_dir=str(tmp_path / "analysis-inputs"),
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    fake_client = GetObjectOnlyFakeS3Client(b"gateway failed\n")
    key = "cases/case-1/uploads/file-1/gateway.log"

    with materialize_analysis_inputs(
        [f"s3://logan/{key}"],
        app_settings,
        s3_client_factory=lambda _: fake_client,
    ) as paths:
        assert Path(paths[0]).read_bytes() == b"gateway failed\n"

    assert fake_client.get_object_calls == [{"Bucket": "logan", "Key": key}]


def test_materialize_analysis_inputs_sanitizes_s3_download_errors(
    tmp_path: Path,
) -> None:
    class FailingFakeS3Client:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            raise RuntimeError(
                f"download failed for {Bucket}/{Key} secret=logan-secret-token"
            )

    app_settings = Settings(
        object_store_backend="s3",
        analysis_input_tmp_dir=str(tmp_path / "analysis-inputs"),
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    key = "cases/case-1/uploads/file-1/secret.log"

    with pytest.raises(ObjectStoreError) as exc_info:
        with materialize_analysis_inputs(
            [f"s3://logan/{key}"],
            app_settings,
            s3_client_factory=lambda _: FailingFakeS3Client(),
        ):
            pass

    message = str(exc_info.value)
    assert message == "S3 download failed"
    assert key not in message
    assert "secret" not in message.lower()


def test_presigned_upload_uses_fake_s3_client_without_network() -> None:
    app_settings = Settings(
        object_store_backend="minio",
        s3_endpoint="http://minio:9000",
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
        s3_presign_expires_seconds=123,
    )
    fake_client = FakeS3Client()
    object_uri = s3_upload_object_uri(
        case_id="case-1",
        file_id="file-1",
        filename="incident.log",
        app_settings=app_settings,
    )

    presigned = create_presigned_upload(
        object_uri,
        content_type="text/plain",
        app_settings=app_settings,
        s3_client_factory=lambda _: fake_client,
    )

    assert presigned.upload_url == "https://minio.example/logan/upload?signature=fake"
    assert presigned.upload_headers == {"content-type": "text/plain"}
    assert presigned.upload_backend == "minio"
    assert presigned.expires_in == 123
    assert fake_client.presign_calls == [
        {
            "operation": "put_object",
            "Params": {
                "Bucket": "logan",
                "Key": "cases/case-1/uploads/file-1/incident.log",
                "ContentType": "text/plain",
            },
            "ExpiresIn": 123,
            "HttpMethod": "PUT",
        }
    ]


def test_step_manifest_writer_puts_s3_object_with_safe_json_body() -> None:
    app_settings = Settings(
        object_store_backend="minio",
        s3_endpoint="http://minio:9000",
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    fake_client = FakeS3Client()
    event = JobEventRecord(
        id="event-1",
        case_id="case-1",
        analysis_run_id="run-1",
        step_name="copilot_annotation",
        event_type="completed",
        status="completed",
        attempt=1,
        idempotency_key="copilot_annotation:attempt:1",
        metadata={
            "annotations": 3,
            "raw_text": "raw secret log line",
            "prompt": "model prompt",
            "token": "gho_secret_token",
            "file_path": "/customer/acme/payment.log",
            "export_types": ["html", "json"],
        },
    )

    written = write_step_manifest(
        event=event,
        app_settings=app_settings,
        s3_client_factory=lambda _: fake_client,
    )

    assert written.object_uri == (
        "s3://logan/cases/case-1/analysis-runs/run-1/steps/copilot_annotation.json"
    )
    assert len(written.sha256) == 64
    assert fake_client.put_object_calls
    put_call = fake_client.put_object_calls[0]
    assert put_call["Bucket"] == "logan"
    assert put_call["Key"] == "cases/case-1/analysis-runs/run-1/steps/copilot_annotation.json"
    assert put_call["ContentType"] == "application/json"
    assert put_call["Metadata"] == {
        "sha256": written.sha256,
        "content-type": "application/json",
    }
    assert len(put_call["Body"]) == written.size_bytes
    assert written.sha256 == hashlib.sha256(put_call["Body"]).hexdigest()
    manifest = json.loads(put_call["Body"])
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


def test_step_manifest_writer_uses_short_local_object_path(tmp_path: Path) -> None:
    app_settings = Settings(local_object_store_dir=str(tmp_path / "object-store"))
    event = JobEventRecord(
        id="event-1",
        case_id="case-" + "1" * 64,
        analysis_run_id="run-" + "2" * 64,
        step_name="representative_sampling",
        event_type="completed",
        status="completed",
        attempt=1,
        idempotency_key="representative_sampling:attempt:1",
        metadata={"samples": 3},
    )

    written = write_step_manifest(event=event, app_settings=app_settings)
    artifact_path = file_uri_to_path(written.object_uri)

    assert artifact_path.exists()
    assert artifact_path.parent.name == "step-artifacts"
    assert artifact_path.name.endswith(".json")
    assert "analysis-runs" not in written.object_uri
    assert len(str(artifact_path)) < len(str(tmp_path / "object-store")) + 100
    assert written.sha256 == hashlib.sha256(artifact_path.read_bytes()).hexdigest()


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


def test_multipart_upload_plan_calculates_part_count() -> None:
    plan = create_multipart_upload_plan(
        size_bytes=129,
        part_size_bytes=64,
        max_parts=10,
    )

    assert plan.size_bytes == 129
    assert plan.part_size_bytes == 64
    assert plan.part_count == 3


def test_multipart_upload_plan_rejects_invalid_or_excessive_parts() -> None:
    try:
        create_multipart_upload_plan(size_bytes=0, part_size_bytes=64, max_parts=10)
    except ValueError as exc:
        assert "size_bytes" in str(exc)
    else:
        raise AssertionError("expected zero-byte multipart upload to be rejected")

    try:
        create_multipart_upload_plan(size_bytes=129, part_size_bytes=64, max_parts=2)
    except ValueError as exc:
        assert "exceeding the maximum" in str(exc)
    else:
        raise AssertionError("expected multipart upload exceeding max parts to be rejected")
