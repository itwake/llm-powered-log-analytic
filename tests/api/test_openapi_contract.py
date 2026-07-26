from __future__ import annotations

import json
from pathlib import Path

from scripts.export_openapi import current_openapi_schema

REQUIRED = {
    "/api/auth/sso/login": {"get"},
    "/api/auth/sso/callback": {"get"},
    "/api/auth/me": {"get"},
    "/api/auth/logout": {"post"},
    "/api/cases": {"get", "post"},
    "/api/cases/{case_id}": {"get", "patch", "delete"},
    "/api/cases/{case_id}/uploads": {"post"},
    "/api/cases/{case_id}/uploads/{file_id}/content": {"put"},
    "/api/cases/{case_id}/analysis-runs": {"get", "post"},
    "/api/cases/{case_id}/analysis-runs/{run_id}": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/cancel": {"post"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/summary": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/temporal": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/logs": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/causal-graph": {"get"},
    "/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary": {"get"},
    "/api/chat/stream": {"post"},
}


def test_openapi_contains_only_the_supported_surface() -> None:
    paths = current_openapi_schema()["paths"]
    for path, methods in REQUIRED.items():
        assert methods <= set(paths[path])
    assert set(paths) == set(REQUIRED)


def test_openapi_snapshot_matches_current_schema() -> None:
    snapshot = json.loads(Path("docs/openapi.snapshot.json").read_text(encoding="utf-8"))
    assert current_openapi_schema() == snapshot
