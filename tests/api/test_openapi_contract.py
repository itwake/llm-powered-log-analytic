from __future__ import annotations

import json
from pathlib import Path

from scripts.export_openapi import current_openapi_schema


REQUIRED_ENDPOINTS: dict[str, set[str]] = {
    "/api/cases": {"get", "post"},
    "/api/cases/{case_id}": {"get"},
    "/api/cases/{case_id}/uploads": {"post"},
    "/api/cases/{case_id}/uploads/{file_id}/content": {"put"},
    "/api/cases/{case_id}/uploads/{file_id}/complete": {"post"},
    "/api/cases/{case_id}/analysis-runs": {"get", "post"},
    "/api/cases/{case_id}/analysis-runs/{run_id}": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/events": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/summary": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/temporal": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/logs": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/causal-graph": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary": {"get", "patch"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/exports": {"post"},
    "/api/cases/{case_id}/feedback": {"post"},
    "/api/chat/stream": {"post"},
}


def test_required_openapi_contract_paths_are_present() -> None:
    schema = current_openapi_schema()
    paths = schema["paths"]

    for path, methods in REQUIRED_ENDPOINTS.items():
        assert path in paths
        assert methods <= set(paths[path])


def test_openapi_snapshot_matches_current_schema() -> None:
    snapshot = json.loads(Path("docs/openapi.snapshot.json").read_text(encoding="utf-8"))

    assert current_openapi_schema() == snapshot
