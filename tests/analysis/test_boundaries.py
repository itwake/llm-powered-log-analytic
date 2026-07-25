from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_analysis_engine_does_not_import_api_package() -> None:
    analysis_root = REPO_ROOT / "apps" / "api" / "logan_analysis"
    engine_files = [
        analysis_root / "models.py",
        analysis_root / "observability.py",
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
