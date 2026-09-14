from __future__ import annotations

from app.config import Settings
from app.services.object_store import (
    EXTENDED_LENGTH_PREFIX,
    extended_length_form,
    file_uri_to_path,
    filesystem_path,
    local_upload_object_uri,
    write_bytes,
)


def test_local_upload_round_trip(tmp_path) -> None:
    settings = Settings(local_object_store_dir=str(tmp_path))
    uri = local_upload_object_uri(
        case_id="case-1",
        file_id="file-1",
        filename="../incident log.txt",
        app_settings=settings,
    )
    stored = write_bytes(uri, b"hello")

    assert stored.size_bytes == 5
    assert len(stored.sha256) == 64
    assert file_uri_to_path(uri).read_bytes() == b"hello"
    assert file_uri_to_path(uri).name == "incident_log.txt"


def test_extended_length_form_prefixes_drive_and_unc_paths_once() -> None:
    drive = r"C:\data\logan\object-store\upload.log"
    unc = r"\\fileserver\share\logan\upload.log"

    assert extended_length_form(drive) == EXTENDED_LENGTH_PREFIX + drive
    assert extended_length_form(unc) == (
        EXTENDED_LENGTH_PREFIX + r"UNC\fileserver\share\logan\upload.log"
    )
    assert extended_length_form(extended_length_form(drive)) == extended_length_form(drive)


def test_filesystem_path_keeps_the_name_and_only_changes_windows_spelling(tmp_path) -> None:
    import os

    target = tmp_path / "uploads" / "logs-from-agent.log"

    spelled = filesystem_path(target)

    assert spelled.name == target.name
    if os.name == "nt":
        assert str(spelled).startswith(EXTENDED_LENGTH_PREFIX)
    else:
        assert spelled == target


def test_ingestion_identity_ignores_the_windows_extended_length_spelling(tmp_path) -> None:
    """The pipeline receives the spelling that opens long paths; stored URIs and file ids must
    not depend on it."""
    import uuid

    from logan_analysis.activities.ingestion import ingest_paths

    source = tmp_path / "service.log"
    source.write_bytes(b"2026-01-01T00:00:00Z ERROR pool exhausted\n")

    [ingested] = ingest_paths([str(filesystem_path(source))])

    assert EXTENDED_LENGTH_PREFIX not in ingested.object_uri
    assert ingested.object_uri == f"file://{source.resolve()}"
    assert ingested.file_id == str(uuid.uuid5(uuid.NAMESPACE_URL, str(source.resolve())))
    assert ingested.original_filename == "service.log"
