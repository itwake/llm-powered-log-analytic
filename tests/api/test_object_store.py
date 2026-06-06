from __future__ import annotations

import os
from pathlib import Path

from app.services.object_store import file_uri_to_path, path_to_file_uri, safe_filename


def test_safe_filename_sanitizes_posix_and_windows_path_separators() -> None:
    assert safe_filename("../evil.log") == "evil.log"
    assert safe_filename("..\\evil.log") == "evil.log"


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
