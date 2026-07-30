from __future__ import annotations

import gzip
import hashlib
import tarfile
import uuid
import zipfile
from pathlib import Path
from typing import Iterable, Iterator

from logan_analysis.models import IngestedFile, RawPhysicalLine


SUPPORTED_EXTENSIONS = {".log", ".txt", ".json", ".jsonl", ".zip", ".gz", ".tar", ".tgz"}
DEFAULT_MAX_INPUT_BYTES = 300 * 1024 * 1024


def _format_limit(max_input_bytes: int) -> str:
    mib = 1024 * 1024
    if max_input_bytes % mib == 0:
        return f"{max_input_bytes // mib} MiB"
    return f"{max_input_bytes} bytes"


def _ensure_input_size(path: Path, max_input_bytes: int) -> None:
    if path.stat().st_size > max_input_bytes:
        raise ValueError(
            f"input exceeds the configured {_format_limit(max_input_bytes)} limit"
        )


def _detect_format(path: Path) -> str:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".tgz") or suffixes.endswith(".tar.gz"):
        return "tgz"
    suffix = path.suffix.lower()
    return suffix.lstrip(".") or "text"


def _iter_paths(paths: Iterable[str | Path]) -> Iterator[Path]:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    yield child
        elif path.is_file():
            yield path


def _decode_line(raw: bytes) -> str:
    try:
        return raw.decode("utf-8").rstrip("\n\r")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace").rstrip("\n\r")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_id(file_id: str, file_path: str, line_number: int, text: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{file_id}:{file_path}:{line_number}:{text}"))


def _physical_line(
    *, file_id: str, file_path: str, line_number: int, text: str, ingestion_order: int
) -> RawPhysicalLine:
    return RawPhysicalLine(
        raw_line_id=_line_id(file_id, file_path, line_number, text),
        file_id=file_id,
        file_path=file_path,
        line_number=line_number,
        raw_text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        ingestion_order=ingestion_order,
    )


def _from_plain_file(
    path: Path,
    ingestion_order_start: int,
    max_input_bytes: int,
) -> tuple[IngestedFile, int]:
    file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(path.resolve())))
    size_bytes = path.stat().st_size
    _ensure_input_size(path, max_input_bytes)
    whole_hash = hashlib.sha256()
    lines: list[RawPhysicalLine] = []
    ingestion_order = ingestion_order_start
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            whole_hash.update(raw)
            lines.append(
                _physical_line(
                    file_id=file_id,
                    file_path=path.name,
                    line_number=line_number,
                    text=_decode_line(raw),
                    ingestion_order=ingestion_order,
                )
            )
            ingestion_order += 1
    return (
        IngestedFile(
            file_id=file_id,
            original_filename=path.name,
            object_uri=f"file://{path.resolve()}",
            size_bytes=size_bytes,
            sha256=whole_hash.hexdigest(),
            detected_format=_detect_format(path),
            lines=lines,
        ),
        ingestion_order,
    )


def _from_gzip(
    path: Path,
    ingestion_order_start: int,
    max_input_bytes: int,
) -> tuple[IngestedFile, int]:
    file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gzip:{path.resolve()}"))
    size_bytes = path.stat().st_size
    whole_hash = _file_sha256(path)
    lines: list[RawPhysicalLine] = []
    ingestion_order = ingestion_order_start
    expanded_size = 0
    with gzip.open(path, "rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            expanded_size += len(raw)
            if expanded_size > max_input_bytes:
                raise ValueError(
                    f"archive content exceeds the configured "
                    f"{_format_limit(max_input_bytes)} limit"
                )
            lines.append(
                _physical_line(
                    file_id=file_id,
                    file_path=path.with_suffix("").name,
                    line_number=line_number,
                    text=_decode_line(raw),
                    ingestion_order=ingestion_order,
                )
            )
            ingestion_order += 1
    return (
        IngestedFile(
            file_id=file_id,
            original_filename=path.name,
            object_uri=f"file://{path.resolve()}",
            size_bytes=size_bytes,
            sha256=whole_hash,
            detected_format="gz",
            lines=lines,
        ),
        ingestion_order,
    )


def _from_zip(
    path: Path,
    ingestion_order_start: int,
    max_input_bytes: int,
) -> tuple[list[IngestedFile], int]:
    files: list[IngestedFile] = []
    ingestion_order = ingestion_order_start
    expanded_size = 0
    with zipfile.ZipFile(path) as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if sum(member.file_size for member in members) > max_input_bytes:
            raise ValueError(
                f"archive content exceeds the configured "
                f"{_format_limit(max_input_bytes)} limit"
            )
        for member in sorted(members, key=lambda item: item.filename):
            name = member.filename
            file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zip:{path.resolve()}:{name}"))
            lines: list[RawPhysicalLine] = []
            whole_hash = hashlib.sha256()
            size_bytes = 0
            with archive.open(member) as handle:
                for line_number, raw in enumerate(handle, start=1):
                    whole_hash.update(raw)
                    size_bytes += len(raw)
                    expanded_size += len(raw)
                    if expanded_size > max_input_bytes:
                        raise ValueError(
                            f"archive content exceeds the configured "
                            f"{_format_limit(max_input_bytes)} limit"
                        )
                    lines.append(
                        _physical_line(
                            file_id=file_id,
                            file_path=name,
                            line_number=line_number,
                            text=_decode_line(raw),
                            ingestion_order=ingestion_order,
                        )
                    )
                    ingestion_order += 1
            files.append(
                IngestedFile(
                    file_id=file_id,
                    original_filename=name,
                    object_uri=f"zip://{path.resolve()}!/{name}",
                    size_bytes=size_bytes,
                    sha256=whole_hash.hexdigest(),
                    detected_format=Path(name).suffix.lower().lstrip(".") or "text",
                    lines=lines,
                )
            )
    return files, ingestion_order


def _from_tar(
    path: Path,
    ingestion_order_start: int,
    max_input_bytes: int,
) -> tuple[list[IngestedFile], int]:
    files: list[IngestedFile] = []
    ingestion_order = ingestion_order_start
    mode = "r:gz" if _detect_format(path) == "tgz" else "r:*"
    expanded_size = 0
    with tarfile.open(path, mode) as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        if sum(member.size for member in members) > max_input_bytes:
            raise ValueError(
                f"archive content exceeds the configured "
                f"{_format_limit(max_input_bytes)} limit"
            )
        for member in sorted(members, key=lambda item: item.name):
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tar:{path.resolve()}:{member.name}"))
            lines: list[RawPhysicalLine] = []
            whole_hash = hashlib.sha256()
            size_bytes = 0
            with extracted:
                for line_number, raw in enumerate(extracted, start=1):
                    whole_hash.update(raw)
                    size_bytes += len(raw)
                    expanded_size += len(raw)
                    if expanded_size > max_input_bytes:
                        raise ValueError(
                            f"archive content exceeds the configured "
                            f"{_format_limit(max_input_bytes)} limit"
                        )
                    lines.append(
                        _physical_line(
                            file_id=file_id,
                            file_path=member.name,
                            line_number=line_number,
                            text=_decode_line(raw),
                            ingestion_order=ingestion_order,
                        )
                    )
                    ingestion_order += 1
            files.append(
                IngestedFile(
                    file_id=file_id,
                    original_filename=member.name,
                    object_uri=f"tar://{path.resolve()}!/{member.name}",
                    size_bytes=size_bytes,
                    sha256=whole_hash.hexdigest(),
                    detected_format=Path(member.name).suffix.lower().lstrip(".") or "text",
                    lines=lines,
                )
            )
    return files, ingestion_order


def ingest_paths(
    paths: Iterable[str | Path],
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
) -> list[IngestedFile]:
    if max_input_bytes <= 0:
        raise ValueError("max_input_bytes must be greater than zero")
    files: list[IngestedFile] = []
    ingestion_order = 0
    for path in _iter_paths(paths):
        _ensure_input_size(path, max_input_bytes)
        detected = _detect_format(path)
        if detected == "zip":
            archive_files, ingestion_order = _from_zip(
                path,
                ingestion_order,
                max_input_bytes,
            )
            files.extend(archive_files)
        elif detected in {"tar", "tgz"}:
            archive_files, ingestion_order = _from_tar(
                path,
                ingestion_order,
                max_input_bytes,
            )
            files.extend(archive_files)
        elif detected == "gz":
            ingested, ingestion_order = _from_gzip(
                path,
                ingestion_order,
                max_input_bytes,
            )
            files.append(ingested)
        elif path.suffix.lower() in SUPPORTED_EXTENSIONS:
            ingested, ingestion_order = _from_plain_file(
                path,
                ingestion_order,
                max_input_bytes,
            )
            files.append(ingested)
    return files
