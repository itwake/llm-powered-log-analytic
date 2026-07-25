from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
STALE_REFERENCES = (
    "docker-compose.quickstart.yml",
    "scripts/full_stack_smoke.py",
    "infra/k8s/",
    "infra/eks/",
    "apps/api/alembic.ini",
    "scripts/evaluate_benchmarks.py",
    "apps/workers",
    "tests/workers",
    "logan_workers",
    "LOGAN_STORE_BACKEND",
    "LOGAN_OBJECT_STORE_BACKEND",
    "LOGAN_ANALYSIS_ORCHESTRATOR",
)
REMOTE_STORAGE_REFERENCES = (
    "s3_client_factory",
    "s3://",
    "LOGAN_S3_",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "MINIO_",
)
ENV_ASSIGNMENT_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", flags=re.MULTILINE)
AUXILIARY_ENV_NAMES = {
    "LOGAN_API_WORKERS",
    "LOGAN_DEMO_API_BASE_URL",
    "LOGAN_DEMO_WEB_BASE_URL",
    "NEXT_PUBLIC_API_BASE_URL",
}


def _documentation_script_and_config_files() -> list[Path]:
    files = [
        REPO_ROOT / ".env.example",
        REPO_ROOT / ".env.full.example",
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "Makefile",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "package.json",
        REPO_ROOT / "pyproject.toml",
        *(REPO_ROOT / ".github" / "workflows").glob("*.yml"),
        *(REPO_ROOT / "docs").glob("*.html"),
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


def test_documentation_and_config_do_not_expose_remote_object_storage() -> None:
    violations: list[str] = []
    for path in _documentation_script_and_config_files():
        content = path.read_text(encoding="utf-8")
        for stale in REMOTE_STORAGE_REFERENCES:
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


def test_python_sources_live_under_the_api_application() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "infra" / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert 'where = ["apps/api"]' in pyproject
    assert 'pythonpath = ["apps/api"]' in pyproject
    assert dockerfile.count("COPY apps/api ./apps/api") == 1
    assert not (REPO_ROOT / "apps" / "workers").exists()
    assert not (REPO_ROOT / "tests" / "workers").exists()
