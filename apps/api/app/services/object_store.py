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


EXTENDED_LENGTH_PREFIX = "\\\\?\\"


def extended_length_form(absolute_path: str) -> str:
    """Return the Windows extended-length form of an absolute path.

    Windows refuses paths longer than 260 characters unless they carry the ``\\\\?\\`` prefix.
    An object-store root a few directories deep plus two identifiers and a long upload name
    crosses that limit easily, and the failure surfaces as a misleading "file not found".
    """
    if absolute_path.startswith(EXTENDED_LENGTH_PREFIX):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return f"{EXTENDED_LENGTH_PREFIX}UNC\\{absolute_path[2:]}"
    return f"{EXTENDED_LENGTH_PREFIX}{absolute_path}"


def filesystem_path(path: Path) -> Path:
    """The path to hand to the operating system for reading or writing ``path``.

    Only Windows needs a different spelling. The ``file://`` object URIs stored in the
    database keep the plain form; convert at the point of filesystem access.
    """
    if os.name != "nt":
        return path
    return Path(extended_length_form(str(path.resolve())))


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
    path = filesystem_path(file_uri_to_path(object_uri))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    sha256, size_bytes = digest_bytes(content)
    return StoredObject(object_uri=object_uri, sha256=sha256, size_bytes=size_bytes)
