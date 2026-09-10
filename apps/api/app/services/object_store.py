from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import Settings, settings


@dataclass(frozen=True)
class StoredObject:
    object_uri: str
    sha256: str
    size_bytes: int


def safe_filename(filename: str | None) -> str:
    value = Path(filename or "upload.bin").name
    value = re.sub(r"[\x00-\x1f\x7f]+", "", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value[:255] or "upload.bin"


def local_upload_path(
    *,
    case_id: str,
    file_id: str,
    filename: str | None,
    app_settings: Settings = settings,
) -> Path:
    return (
        Path(app_settings.local_object_store_dir)
        / "cases"
        / safe_filename(case_id)
        / "uploads"
        / safe_filename(file_id)
        / safe_filename(filename)
    )


def path_to_file_uri(path: Path) -> str:
    return f"file://{path.resolve().as_posix()}"


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


def file_uri_to_path(object_uri: str) -> Path:
    if not object_uri.startswith("file://"):
        raise ValueError("object URI is not file-backed")
    parsed = urlparse(object_uri)
    if parsed.netloc and parsed.path:
        path_text = f"{parsed.netloc}{parsed.path}"
    else:
        path_text = parsed.netloc or parsed.path
    path_text = unquote(path_text)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path_text):
        path_text = path_text[1:]
    return Path(path_text.replace("/", os.sep))


def digest_bytes(content: bytes) -> tuple[str, int]:
    return hashlib.sha256(content).hexdigest(), len(content)


def write_bytes(object_uri: str, content: bytes) -> StoredObject:
    path = file_uri_to_path(object_uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    sha256, size_bytes = digest_bytes(content)
    return StoredObject(object_uri=object_uri, sha256=sha256, size_bytes=size_bytes)
