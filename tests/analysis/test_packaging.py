from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_removed_infrastructure_is_not_packaged() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    dependencies = [
        *project["dependencies"],
        *(
            dependency
            for extra in project.get("optional-dependencies", {}).values()
            for dependency in extra
        ),
    ]
    dependency_text = "\n".join(dependencies).lower()

    for removed in (
        "boto3",
        "botocore",
        "drain3",
        "minio",
        "opentelemetry",
        "s3fs",
        "temporalio",
    ):
        assert removed not in dependency_text


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
