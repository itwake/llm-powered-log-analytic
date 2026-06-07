from __future__ import annotations

import gzip
import hashlib
import tarfile
import uuid
import zipfile
from pathlib import Path
from typing import Iterable, Iterator

from logan_workers.models import IngestedFile, RawPhysicalLine


SUPPORTED_EXTENSIONS = {".log", ".txt", ".json", ".jsonl", ".zip", ".gz", ".tar", ".tgz"}


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


def _decode_lines(binary_lines: Iterable[bytes]) -> Iterator[str]:
    for raw in binary_lines:
        try:
            yield raw.decode("utf-8").rstrip("\n\r")
        except UnicodeDecodeError:
            yield raw.decode("latin-1", errors="replace").rstrip("\n\r")


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


def _from_plain_file(path: Path, ingestion_order_start: int) -> tuple[IngestedFile, int]:
    file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(path.resolve())))
    size_bytes = path.stat().st_size
    whole_hash = hashlib.sha256()
    lines: list[RawPhysicalLine] = []
    ingestion_order = ingestion_order_start
    with path.open("rb") as handle:
        raw_lines = list(handle)
    for raw in raw_lines:
        whole_hash.update(raw)
    for line_number, text in enumerate(_decode_lines(raw_lines), start=1):
        lines.append(
            _physical_line(
                file_id=file_id,
                file_path=path.name,
                line_number=line_number,
                text=text,
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


def _from_gzip(path: Path, ingestion_order_start: int) -> tuple[IngestedFile, int]:
    file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gzip:{path.resolve()}"))
    raw_bytes = path.read_bytes()
    whole_hash = hashlib.sha256(raw_bytes).hexdigest()
    lines: list[RawPhysicalLine] = []
    ingestion_order = ingestion_order_start
    with gzip.open(path, "rb") as handle:
        for line_number, text in enumerate(_decode_lines(handle), start=1):
            lines.append(
                _physical_line(
                    file_id=file_id,
                    file_path=path.with_suffix("").name,
                    line_number=line_number,
                    text=text,
                    ingestion_order=ingestion_order,
                )
            )
            ingestion_order += 1
    return (
        IngestedFile(
            file_id=file_id,
            original_filename=path.name,
            object_uri=f"file://{path.resolve()}",
            size_bytes=len(raw_bytes),
            sha256=whole_hash,
            detected_format="gz",
            lines=lines,
        ),
        ingestion_order,
    )


def _from_zip(path: Path, ingestion_order_start: int) -> tuple[list[IngestedFile], int]:
    files: list[IngestedFile] = []
    ingestion_order = ingestion_order_start
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/"):
                continue
            file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zip:{path.resolve()}:{name}"))
            raw_bytes = archive.read(name)
            lines: list[RawPhysicalLine] = []
            for line_number, text in enumerate(_decode_lines(raw_bytes.splitlines(keepends=True)), start=1):
                lines.append(
                    _physical_line(
                        file_id=file_id,
                        file_path=name,
                        line_number=line_number,
                        text=text,
                        ingestion_order=ingestion_order,
                    )
                )
                ingestion_order += 1
            files.append(
                IngestedFile(
                    file_id=file_id,
                    original_filename=name,
                    object_uri=f"zip://{path.resolve()}!/{name}",
                    size_bytes=len(raw_bytes),
                    sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    detected_format=Path(name).suffix.lower().lstrip(".") or "text",
                    lines=lines,
                )
            )
    return files, ingestion_order


def _from_tar(path: Path, ingestion_order_start: int) -> tuple[list[IngestedFile], int]:
    files: list[IngestedFile] = []
    ingestion_order = ingestion_order_start
    mode = "r:gz" if _detect_format(path) == "tgz" else "r:*"
    with tarfile.open(path, mode) as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw_bytes = extracted.read()
            file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tar:{path.resolve()}:{member.name}"))
            lines: list[RawPhysicalLine] = []
            for line_number, text in enumerate(_decode_lines(raw_bytes.splitlines(keepends=True)), start=1):
                lines.append(
                    _physical_line(
                        file_id=file_id,
                        file_path=member.name,
                        line_number=line_number,
                        text=text,
                        ingestion_order=ingestion_order,
                    )
                )
                ingestion_order += 1
            files.append(
                IngestedFile(
                    file_id=file_id,
                    original_filename=member.name,
                    object_uri=f"tar://{path.resolve()}!/{member.name}",
                    size_bytes=len(raw_bytes),
                    sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    detected_format=Path(member.name).suffix.lower().lstrip(".") or "text",
                    lines=lines,
                )
            )
    return files, ingestion_order


def ingest_paths(paths: Iterable[str | Path]) -> list[IngestedFile]:
    files: list[IngestedFile] = []
    ingestion_order = 0
    for path in _iter_paths(paths):
        detected = _detect_format(path)
        if detected == "zip":
            archive_files, ingestion_order = _from_zip(path, ingestion_order)
            files.extend(archive_files)
        elif detected in {"tar", "tgz"}:
            archive_files, ingestion_order = _from_tar(path, ingestion_order)
            files.extend(archive_files)
        elif detected == "gz":
            ingested, ingestion_order = _from_gzip(path, ingestion_order)
            files.append(ingested)
        elif path.suffix.lower() in SUPPORTED_EXTENSIONS:
            ingested, ingestion_order = _from_plain_file(path, ingestion_order)
            files.append(ingested)
    return files
