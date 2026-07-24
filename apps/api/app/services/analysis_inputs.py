from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app.services.object_store import file_uri_to_path


@contextmanager
def materialize_analysis_inputs(paths: list[str]) -> Iterator[list[str]]:
    yield [str(file_uri_to_path(path)) if path.startswith("file://") else path for path in paths]
