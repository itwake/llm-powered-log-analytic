from __future__ import annotations

from app.config import Settings
from app.services.object_store import file_uri_to_path, local_upload_object_uri, write_bytes


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
