from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from urllib.parse import urlsplit

from app.config import Settings, settings
from app.services.object_store import (
    ObjectStoreError,
    S3ClientFactory,
    file_uri_to_path,
    get_s3_client,
    parse_s3_object_uri,
    safe_filename,
)


def _path_backend(path: str) -> str:
    scheme = urlsplit(path).scheme.lower()
    if scheme == "s3":
        return "s3"
    if scheme == "file":
        return "file"
    return "path"


def analysis_input_backend_counts(paths: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in paths:
        backend = _path_backend(path)
        counts[backend] = counts.get(backend, 0) + 1
    return counts


def _materialized_s3_path(*, root: Path, index: int, key: str) -> Path:
    filename = safe_filename(Path(key).name)
    directory = root / f"{index:04d}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


def _body_bytes(body: Any) -> bytes:
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if hasattr(body, "read"):
        content = body.read()
        if isinstance(content, bytes):
            return content
        if isinstance(content, bytearray):
            return bytes(content)
    raise ObjectStoreError("S3 get_object response Body was not readable")


def _download_s3_object(
    *,
    client: Any,
    bucket: str,
    key: str,
    destination: Path,
) -> None:
    try:
        download_file = getattr(client, "download_file", None)
        if callable(download_file):
            download_file(Bucket=bucket, Key=key, Filename=str(destination))
            return
        response = client.get_object(Bucket=bucket, Key=key)
        body = response.get("Body") if isinstance(response, dict) else None
        destination.write_bytes(_body_bytes(body))
    except ObjectStoreError:
        raise
    except Exception as exc:
        raise ObjectStoreError("S3 download failed") from exc


@contextmanager
def materialize_analysis_inputs(
    paths: list[str],
    app_settings: Settings = settings,
    *,
    run_id: str | None = None,
    s3_client_factory: S3ClientFactory | None = None,
) -> Iterator[list[str]]:
    materialized: list[str] = []
    temporary_directory: TemporaryDirectory[str] | None = None
    try:
        for index, path in enumerate(paths, start=1):
            backend = _path_backend(path)
            if backend == "file":
                materialized.append(str(file_uri_to_path(path)))
                continue
            if backend != "s3":
                materialized.append(path)
                continue

            try:
                bucket, key = parse_s3_object_uri(path)
            except ValueError as exc:
                raise ObjectStoreError("S3 input URI is invalid") from exc
            if temporary_directory is None:
                tmp_root = Path(app_settings.analysis_input_tmp_dir)
                tmp_root.mkdir(parents=True, exist_ok=True)
                prefix = f"{safe_filename(run_id or 'run')}-"
                temporary_directory = TemporaryDirectory(prefix=prefix, dir=tmp_root)
            destination = _materialized_s3_path(
                root=Path(temporary_directory.name),
                index=index,
                key=key,
            )
            client = get_s3_client(
                app_settings,
                s3_client_factory=s3_client_factory,
            )
            _download_s3_object(
                client=client,
                bucket=bucket,
                key=key,
                destination=destination,
            )
            materialized.append(str(destination))
        yield materialized
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()
