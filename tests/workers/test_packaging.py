from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_drain3_is_optional_dependency() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    extras = pyproject["project"]["optional-dependencies"]

    assert not any(dependency.lower().startswith("drain3") for dependency in dependencies)
    assert any(dependency.lower().startswith("drain3") for dependency in extras["drain3"])


def test_analysis_engine_does_not_import_api_package() -> None:
    worker_root = REPO_ROOT / "apps" / "workers" / "logan_workers"
    engine_files = [
        worker_root / "models.py",
        worker_root / "observability.py",
        worker_root / "pipeline.py",
        worker_root / "ports.py",
        *(worker_root / "algorithms").glob("*.py"),
        *(
            path
            for path in (worker_root / "activities").glob("*.py")
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
