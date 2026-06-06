from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, settings


@dataclass(frozen=True)
class StoredObject:
    path: Path
    object_uri: str
    sha256: str
    size_bytes: int


def object_store_backend(app_settings: Settings = settings) -> str:
    return (app_settings.object_store_backend or "local").lower()


def is_local_backend(app_settings: Settings = settings) -> bool:
    return object_store_backend(app_settings) == "local"


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


def stat_object(object_uri: str) -> StoredObject:
    path = file_uri_to_path(object_uri)
    sha256, size_bytes = digest_file(path)
    return StoredObject(
        path=path,
        object_uri=path_to_file_uri(path),
        sha256=sha256,
        size_bytes=size_bytes,
    )
