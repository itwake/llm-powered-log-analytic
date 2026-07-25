from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ENV_ASSIGNMENT_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", flags=re.MULTILINE)
AUXILIARY_ENV_NAMES = {
    "LOGAN_API_WORKERS",
    "LOGAN_DEMO_API_BASE_URL",
    "LOGAN_DEMO_WEB_BASE_URL",
    "NEXT_PUBLIC_API_BASE_URL",
}


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


def _active_env_values(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        values[name] = value
    return values


def test_complete_environment_reference_tracks_settings() -> None:
    config = (REPO_ROOT / "apps" / "api" / "app" / "config.py").read_text(encoding="utf-8")
    minimal = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    complete = (REPO_ROOT / ".env.full.example").read_text(encoding="utf-8")

    settings_env_names = set(re.findall(r'"(LOGAN_[A-Z0-9_]+)"', config))
    documented_env_names = set(ENV_ASSIGNMENT_RE.findall(complete))

    assert settings_env_names <= documented_env_names
    assert AUXILIARY_ENV_NAMES <= documented_env_names
    assert _active_env_values(complete) == _active_env_values(minimal)
    assert "LOGAN_LOCAL_OBJECT_STORE_DIR=.logan/object-store" in minimal


def test_python_sources_use_the_api_package_root() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "infra" / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert 'where = ["apps/api"]' in pyproject
    assert 'pythonpath = ["apps/api"]' in pyproject
    assert dockerfile.count("COPY apps/api ./apps/api") == 1
    assert (REPO_ROOT / "apps" / "api" / "app").is_dir()
    assert (REPO_ROOT / "apps" / "api" / "logan_analysis").is_dir()
    assert (REPO_ROOT / "tests" / "analysis").is_dir()
