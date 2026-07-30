from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

from logan_analysis.activities.preprocessing import _fast_normalized_line
from logan_analysis.models import NormalizedLogLine

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_analysis_engine_does_not_import_api_package() -> None:
    analysis_root = REPO_ROOT / "apps" / "api" / "logan_analysis"
    engine_files = [
        analysis_root / "models.py",
        analysis_root / "pipeline.py",
        analysis_root / "ports.py",
        *(analysis_root / "algorithms").glob("*.py"),
        *(
            path
            for path in (analysis_root / "activities").glob("*.py")
            if path.name != "analysis.py"
        ),
    ]

    violations: list[str] = []
    for path in engine_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app" or alias.name.startswith("app."):
                        violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert violations == []


def test_fast_normalized_line_matches_validated_construction() -> None:
    """Pin the pydantic slot layout the fast construction path relies on.

    Ingestion, multiline merging, and preprocessing assemble model instances via
    object.__new__ plus direct slot assignment for speed; if a pydantic upgrade
    changes the instance layout or field semantics, this test must fail.
    """
    values = {
        "log_id": "line-1",
        "raw_log_id": "line-1",
        "case_id": "case-1",
        "analysis_run_id": "run-1",
        "file_id": "file-1",
        "file_path": "app.log",
        "line_number": 7,
        "line_numbers": [7, 8],
        "timestamp": datetime(2026, 6, 22, 7, 37, 41, tzinfo=UTC),
        "timestamp_quality": "parsed",
        "level": "ERROR",
        "service": "UPDTANNC",
        "message": "boom",
        "normalized_message": "",
        "redacted_message": "boom",
        "parsed_fields": {"stack_trace_lines": [7, 8]},
        "parser_name": "logan_regex_v1",
        "parser_confidence": 0.9,
        "ingestion_order": 3,
        "template_id": None,
        "template_text": "boom",
        "golden_signal": "unknown",
        "fault_categories": [],
        "entities": {},
        "severity_score": 0.0,
        "confidence": 0.0,
    }
    assert set(values) == set(NormalizedLogLine.model_fields)

    fast = _fast_normalized_line(dict(values))
    validated = NormalizedLogLine(**values)
    assert fast.model_dump() == validated.model_dump()
    assert fast.model_dump_json() == validated.model_dump_json()

    # Instances built through the fast path must still behave like models.
    fast.template_id = "template-1"
    assert fast.model_copy(update={"line_number": 8}).line_number == 8
    assert fast.evidence_ref().log_id == "line-1"
