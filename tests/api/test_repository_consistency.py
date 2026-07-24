from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
STALE_REFERENCES = (
    ".env.full.example",
    "docker-compose.quickstart.yml",
    "scripts/full_stack_smoke.py",
    "infra/k8s/",
    "infra/eks/",
    "apps/api/alembic.ini",
    "scripts/evaluate_benchmarks.py",
    "LOGAN_STORE_BACKEND",
    "LOGAN_OBJECT_STORE_BACKEND",
    "LOGAN_ANALYSIS_ORCHESTRATOR",
)


def _documentation_script_and_config_files() -> list[Path]:
    files = [
        REPO_ROOT / ".env.example",
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "Makefile",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "package.json",
        REPO_ROOT / "pyproject.toml",
        *(REPO_ROOT / ".github" / "workflows").glob("*.yml"),
        *(REPO_ROOT / "docs").glob("*.md"),
        *(REPO_ROOT / "infra" / "docker").glob("*.Dockerfile"),
        *(REPO_ROOT / "scripts").glob("*.py"),
        *(REPO_ROOT / "scripts").glob("*.js"),
        *(REPO_ROOT / "scripts").glob("*.ps1"),
        *(REPO_ROOT / "scripts").glob("*.bat"),
        *(REPO_ROOT / "apps").glob("*/README.md"),
    ]
    return sorted(path for path in files if path.is_file())


def test_documentation_and_scripts_do_not_reference_removed_entrypoints() -> None:
    violations: list[str] = []
    for path in _documentation_script_and_config_files():
        content = path.read_text(encoding="utf-8")
        for stale in STALE_REFERENCES:
            if stale in content:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {stale}")

    assert violations == []


def test_relative_markdown_links_resolve() -> None:
    missing: list[str] = []
    markdown_files = [
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "README.md",
        *(REPO_ROOT / "docs").glob("*.md"),
        *(REPO_ROOT / "apps").glob("*/README.md"),
    ]
    for path in markdown_files:
        content = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_RE.finditer(content):
            target = match.group(1).split("#", 1)[0].strip().strip("<>")
            if not target or re.match(r"^(?:[a-z]+:|/)", target, flags=re.IGNORECASE):
                continue
            resolved = (path.parent / unquote(target)).resolve()
            if not resolved.exists():
                missing.append(f"{path.relative_to(REPO_ROOT)} -> {target}")

    assert missing == []


def test_local_entrypoints_use_reproducible_checks() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    powershell = (REPO_ROOT / "scripts" / "local.ps1").read_text(encoding="utf-8")
    batch = (REPO_ROOT / "scripts" / "local.bat").read_text(encoding="utf-8")

    assert "ruff check --select F" in makefile
    assert "ruff check --select F" in workflow
    assert "ruff check --select F" in readme
    assert "ruff check --select F" in contributing
    assert 'pip install -e ".[dev]"' in makefile
    assert 'pip install -e ".[dev]" -c constraints.txt' in workflow
    assert "$(NPM) ci" in makefile
    assert "npm ci" in workflow
    assert "npm ci" in powershell
    assert "npm ci" in batch
    assert "Node.js 22+" in powershell
    assert "Node.js 22+" in batch
    assert not (REPO_ROOT / "apps" / "api" / "alembic.ini").exists()


def test_documented_python_lint_command_matches_ci() -> None:
    stale_command = "ruff check apps tests scripts"
    violations = [
        str(path.relative_to(REPO_ROOT))
        for path in _documentation_script_and_config_files()
        if stale_command in path.read_text(encoding="utf-8")
    ]

    assert violations == []
