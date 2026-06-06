from __future__ import annotations

import hashlib
import math
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit

from app.config import Settings, settings


class ObjectStoreError(RuntimeError):
    """Base error for object-store adapter failures."""


class ObjectStoreConfigurationError(ObjectStoreError):
    """Raised when the selected object-store backend is not configured."""


@dataclass(frozen=True)
class StoredObject:
    path: Path | None
    object_uri: str
    sha256: str | None
    size_bytes: int


@dataclass(frozen=True)
class PresignedUpload:
    upload_url: str
    upload_headers: dict[str, str]
    upload_backend: str
    expires_in: int


@dataclass(frozen=True)
class MultipartUploadPlan:
    size_bytes: int
    part_size_bytes: int
    part_count: int


@dataclass(frozen=True)
class MultipartPartUploadUrl:
    part_number: int
    upload_url: str
    upload_headers: dict[str, str]


@dataclass(frozen=True)
class CompletedMultipartUploadPart:
    part_number: int
    etag: str


@dataclass(frozen=True)
class UploadedMultipartPart:
    part_number: int
    etag: str
    size_bytes: int


S3_BACKENDS = frozenset({"s3", "minio"})
S3ClientFactory = Callable[[Settings], Any]
_S3_CLIENT_CACHE: dict[tuple[object, ...], Any] = {}


def object_store_backend(app_settings: Settings = settings) -> str:
    return (app_settings.object_store_backend or "local").lower()


def is_local_backend(app_settings: Settings = settings) -> bool:
    return object_store_backend(app_settings) == "local"


def is_s3_backend(app_settings: Settings = settings) -> bool:
    return object_store_backend(app_settings) in S3_BACKENDS


def safe_filename(filename: str | None) -> str:
    name = Path((filename or "").replace("\\", "/")).name.strip()
    name = "".join(
        character for character in name if ord(character) >= 32 and ord(character) != 127
    )
    if name in {"", ".", ".."}:
        return "upload.bin"
    return name


def local_upload_path(
    *,
    case_id: str,
    file_id: str,
    filename: str | None,
    app_settings: Settings = settings,
) -> Path:
    root = Path(app_settings.local_object_store_dir)
    return root / "cases" / case_id / "uploads" / file_id / safe_filename(filename)


def local_upload_object_uri(
    *,
    case_id: str,
    file_id: str,
    filename: str | None,
    app_settings: Settings = settings,
) -> str:
    return path_to_file_uri(
        local_upload_path(
            case_id=case_id,
            file_id=file_id,
            filename=filename,
            app_settings=app_settings,
        )
    )


def _safe_key_segment(value: str | None, fallback: str) -> str:
    segment = safe_filename(value)
    return fallback if segment == "upload.bin" else segment


def s3_upload_key(*, case_id: str, file_id: str, filename: str | None) -> str:
    return "/".join(
        [
            "cases",
            _safe_key_segment(case_id, "case"),
            "uploads",
            _safe_key_segment(file_id, "file"),
            safe_filename(filename),
        ]
    )


def s3_object_uri(*, bucket: str, key: str) -> str:
    if not bucket:
        raise ObjectStoreConfigurationError("LOGAN_S3_BUCKET is required for S3 uploads")
    if not key or key.startswith("/"):
        raise ValueError("S3 object key must be a non-empty relative key")
    return f"s3://{bucket}/{quote(key, safe='/')}"


def parse_s3_object_uri(object_uri: str) -> tuple[str, str]:
    parsed = urlsplit(object_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ValueError("object URI is not S3-backed")
    return parsed.netloc, unquote(parsed.path.lstrip("/"))


def require_s3_settings(app_settings: Settings = settings) -> None:
    missing = [
        name
        for name, value in (
            ("LOGAN_S3_BUCKET", app_settings.s3_bucket),
            ("LOGAN_S3_ACCESS_KEY", app_settings.s3_access_key),
            ("LOGAN_S3_SECRET_KEY", app_settings.s3_secret_key),
        )
        if not value
    ]
    if object_store_backend(app_settings) == "minio" and not app_settings.s3_endpoint:
        missing.append("LOGAN_S3_ENDPOINT")
    if missing:
        raise ObjectStoreConfigurationError(
            f"S3 object-store backend is missing required setting(s): {', '.join(missing)}"
        )


def s3_upload_object_uri(
    *,
    case_id: str,
    file_id: str,
    filename: str | None,
    app_settings: Settings = settings,
) -> str:
    require_s3_settings(app_settings)
    assert app_settings.s3_bucket is not None
    return s3_object_uri(
        bucket=app_settings.s3_bucket,
        key=s3_upload_key(case_id=case_id, file_id=file_id, filename=filename),
    )


def _s3_client_cache_key(app_settings: Settings) -> tuple[object, ...]:
    return (
        app_settings.s3_endpoint,
        app_settings.s3_access_key,
        app_settings.s3_secret_key,
        app_settings.s3_region,
        app_settings.s3_force_path_style,
    )


def _create_s3_client(app_settings: Settings) -> Any:
    require_s3_settings(app_settings)
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise ObjectStoreConfigurationError(
            "S3 object-store backend requires boto3; install the project dependencies"
        ) from exc
    config = Config(
        s3={"addressing_style": "path" if app_settings.s3_force_path_style else "auto"}
    )
    client_args: dict[str, Any] = {
        "aws_access_key_id": app_settings.s3_access_key,
        "aws_secret_access_key": app_settings.s3_secret_key,
        "region_name": app_settings.s3_region,
        "config": config,
    }
    if app_settings.s3_endpoint:
        client_args["endpoint_url"] = app_settings.s3_endpoint
    return boto3.client("s3", **client_args)


def get_s3_client(
    app_settings: Settings = settings,
    *,
    s3_client_factory: S3ClientFactory | None = None,
) -> Any:
    if s3_client_factory is not None:
        require_s3_settings(app_settings)
        return s3_client_factory(app_settings)
    key = _s3_client_cache_key(app_settings)
    client = _S3_CLIENT_CACHE.get(key)
    if client is None:
        client = _create_s3_client(app_settings)
        _S3_CLIENT_CACHE[key] = client
    return client


def create_presigned_upload(
    object_uri: str,
    *,
    content_type: str | None = None,
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> PresignedUpload:
    bucket, key = parse_s3_object_uri(object_uri)
    require_s3_settings(app_settings)
    params: dict[str, Any] = {"Bucket": bucket, "Key": key}
    upload_headers: dict[str, str] = {}
    if content_type:
        params["ContentType"] = content_type
        upload_headers["content-type"] = content_type
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    upload_url = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=app_settings.s3_presign_expires_seconds,
        HttpMethod="PUT",
    )
    return PresignedUpload(
        upload_url=str(upload_url),
        upload_headers=upload_headers,
        upload_backend=object_store_backend(app_settings),
        expires_in=app_settings.s3_presign_expires_seconds,
    )


def create_multipart_upload_plan(
    *,
    size_bytes: int,
    part_size_bytes: int,
    max_parts: int,
) -> MultipartUploadPlan:
    if size_bytes <= 0:
        raise ValueError("multipart uploads require size_bytes greater than 0")
    if part_size_bytes <= 0:
        raise ValueError("multipart part size must be greater than 0")
    if max_parts <= 0:
        raise ValueError("multipart max parts must be greater than 0")
    part_count = math.ceil(size_bytes / part_size_bytes)
    if part_count > max_parts:
        raise ValueError(
            f"multipart upload requires {part_count} parts, exceeding the maximum of {max_parts}"
        )
    return MultipartUploadPlan(
        size_bytes=size_bytes,
        part_size_bytes=part_size_bytes,
        part_count=part_count,
    )


def _raise_s3_operation_error(operation: str, error: Exception) -> None:
    code = _s3_error_code(error)
    suffix = f" ({code})" if code else ""
    raise ObjectStoreError(f"S3 {operation} failed{suffix}") from error


def create_multipart_upload(
    object_uri: str,
    *,
    content_type: str | None = None,
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> str:
    bucket, key = parse_s3_object_uri(object_uri)
    require_s3_settings(app_settings)
    params: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if content_type:
        params["ContentType"] = content_type
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    try:
        response = client.create_multipart_upload(**params)
    except Exception as exc:
        _raise_s3_operation_error("create_multipart_upload", exc)
    upload_id = response.get("UploadId") if isinstance(response, dict) else None
    if not upload_id:
        raise ObjectStoreError("S3 create_multipart_upload response did not include UploadId")
    return str(upload_id)


def create_multipart_part_urls(
    object_uri: str,
    *,
    multipart_upload_id: str,
    part_count: int,
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> list[MultipartPartUploadUrl]:
    if part_count <= 0:
        raise ValueError("multipart part count must be greater than 0")
    bucket, key = parse_s3_object_uri(object_uri)
    require_s3_settings(app_settings)
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    parts: list[MultipartPartUploadUrl] = []
    for part_number in range(1, part_count + 1):
        params = {
            "Bucket": bucket,
            "Key": key,
            "UploadId": multipart_upload_id,
            "PartNumber": part_number,
        }
        try:
            upload_url = client.generate_presigned_url(
                "upload_part",
                Params=params,
                ExpiresIn=app_settings.s3_presign_expires_seconds,
                HttpMethod="PUT",
            )
        except Exception as exc:
            _raise_s3_operation_error("generate_presigned_upload_part_url", exc)
        parts.append(
            MultipartPartUploadUrl(
                part_number=part_number,
                upload_url=str(upload_url),
                upload_headers={},
            )
        )
    return parts


def complete_multipart_upload(
    object_uri: str,
    *,
    multipart_upload_id: str,
    parts: list[CompletedMultipartUploadPart],
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> dict[str, Any]:
    bucket, key = parse_s3_object_uri(object_uri)
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    multipart_payload = {
        "Parts": [
            {"PartNumber": part.part_number, "ETag": part.etag}
            for part in parts
        ]
    }
    try:
        response = client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=multipart_upload_id,
            MultipartUpload=multipart_payload,
        )
    except Exception as exc:
        _raise_s3_operation_error("complete_multipart_upload", exc)
    return dict(response or {})


def abort_multipart_upload(
    object_uri: str,
    *,
    multipart_upload_id: str,
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> None:
    bucket, key = parse_s3_object_uri(object_uri)
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    try:
        client.abort_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=multipart_upload_id,
        )
    except Exception as exc:
        if _s3_error_code(exc) in {"404", "NoSuchUpload", "NotFound"}:
            return
        _raise_s3_operation_error("abort_multipart_upload", exc)


def list_multipart_parts(
    object_uri: str,
    *,
    multipart_upload_id: str,
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> list[UploadedMultipartPart]:
    bucket, key = parse_s3_object_uri(object_uri)
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    request: dict[str, Any] = {"Bucket": bucket, "Key": key, "UploadId": multipart_upload_id}
    uploaded_parts: list[UploadedMultipartPart] = []
    while True:
        try:
            response = client.list_parts(**request)
        except Exception as exc:
            if _s3_error_code(exc) in {"404", "NoSuchUpload", "NotFound"}:
                raise FileNotFoundError(object_uri) from exc
            _raise_s3_operation_error("list_parts", exc)
        for part in response.get("Parts") or []:
            part_number = part.get("PartNumber")
            etag = part.get("ETag")
            size = part.get("Size")
            if not isinstance(part_number, int) or not etag or not isinstance(size, int):
                raise ObjectStoreError("S3 list_parts response included an invalid part")
            uploaded_parts.append(
                UploadedMultipartPart(
                    part_number=part_number,
                    etag=str(etag),
                    size_bytes=size,
                )
            )
        if not response.get("IsTruncated"):
            break
        next_marker = response.get("NextPartNumberMarker")
        if not isinstance(next_marker, int):
            raise ObjectStoreError("S3 list_parts response did not include NextPartNumberMarker")
        request["PartNumberMarker"] = next_marker
    return sorted(uploaded_parts, key=lambda part: part.part_number)


def _s3_error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        error_payload = response.get("Error")
        if isinstance(error_payload, dict) and error_payload.get("Code"):
            return str(error_payload["Code"])
        metadata = response.get("ResponseMetadata")
        if isinstance(metadata, dict) and metadata.get("HTTPStatusCode"):
            return str(metadata["HTTPStatusCode"])
    return str(getattr(error, "code", "")) or None


def stat_s3_object(
    object_uri: str,
    *,
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> StoredObject:
    bucket, key = parse_s3_object_uri(object_uri)
    client = get_s3_client(app_settings, s3_client_factory=s3_client_factory)
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except FileNotFoundError:
        raise
    except Exception as exc:
        if _s3_error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(object_uri) from exc
        raise
    metadata = response.get("Metadata") or {}
    sha256 = metadata.get("sha256") if isinstance(metadata, dict) else None
    content_length = response.get("ContentLength")
    if not isinstance(content_length, int):
        raise ObjectStoreError("S3 head_object response did not include ContentLength")
    return StoredObject(
        path=None,
        object_uri=s3_object_uri(bucket=bucket, key=key),
        sha256=str(sha256) if sha256 else None,
        size_bytes=content_length,
    )


def path_to_file_uri(path: Path) -> str:
    return f"file://{path.resolve().as_posix()}"


def file_uri_to_path(object_uri: str) -> Path:
    if not object_uri.startswith("file://"):
        raise ValueError("object URI is not file-backed")
    path_text = object_uri.removeprefix("file://")
    if os.name == "nt" and path_text.startswith("/") and _has_windows_drive(path_text[1:]):
        path_text = path_text[1:]
    return Path(path_text)


def _has_windows_drive(path_text: str) -> bool:
    return len(path_text) >= 2 and path_text[0].isalpha() and path_text[1] == ":"


def digest_bytes(content: bytes) -> tuple[str, int]:
    return hashlib.sha256(content).hexdigest(), len(content)


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size_bytes += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size_bytes


def write_bytes(object_uri: str, content: bytes) -> StoredObject:
    path = file_uri_to_path(object_uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha256, size_bytes = digest_bytes(content)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_bytes(content)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return StoredObject(
        path=path,
        object_uri=path_to_file_uri(path),
        sha256=sha256,
        size_bytes=size_bytes,
    )


def stat_object(
    object_uri: str,
    *,
    app_settings: Settings = settings,
    s3_client_factory: S3ClientFactory | None = None,
) -> StoredObject:
    if object_uri.startswith("s3://"):
        return stat_s3_object(
            object_uri,
            app_settings=app_settings,
            s3_client_factory=s3_client_factory,
        )
    path = file_uri_to_path(object_uri)
    sha256, size_bytes = digest_file(path)
    return StoredObject(
        path=path,
        object_uri=path_to_file_uri(path),
        sha256=sha256,
        size_bytes=size_bytes,
    )
