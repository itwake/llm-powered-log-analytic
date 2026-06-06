from __future__ import annotations

import os
from pathlib import Path

from app.config import Settings
from app.services.object_store import (
    create_multipart_upload_plan,
    create_presigned_upload,
    file_uri_to_path,
    parse_s3_object_uri,
    path_to_file_uri,
    s3_upload_key,
    s3_upload_object_uri,
    safe_filename,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.presign_calls: list[dict[str, object]] = []

    def generate_presigned_url(self, operation: str, **kwargs: object) -> str:
        self.presign_calls.append({"operation": operation, **kwargs})
        return "https://minio.example/logan/upload?signature=fake"


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
