from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ENV = re.compile(r"^\s*#?\s*((?:LOGAN|NEXT_PUBLIC)_[A-Z0-9_]+)=", re.MULTILINE)
RUNTIME_ENV = re.compile(r"\b((?:LOGAN|NEXT_PUBLIC)_[A-Z0-9_]+)\b")


def test_relative_markdown_links_resolve() -> None:
    missing: list[str] = []
    files = [
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        *(ROOT / "docs").glob("*.md"),
        *(ROOT / "apps").glob("*/README.md"),
    ]
    for path in files:
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            target = target.split("#", 1)[0].strip().strip("<>")
            if not target or re.match(r"^(?:[a-z]+:|/)", target, re.I):
                continue
            if not (path.parent / unquote(target)).resolve().exists():
                missing.append(f"{path.relative_to(ROOT)} -> {target}")
    assert missing == []


def test_full_environment_example_covers_runtime_settings() -> None:
    runtime_files = [
        *(ROOT / "apps/api/app").rglob("*.py"),
        *(ROOT / "apps/web/src").rglob("*.ts"),
        ROOT / "docker-compose.yml",
        *(ROOT / "infra/docker").glob("*"),
    ]
    runtime_settings = {
        name
        for path in runtime_files
        for name in RUNTIME_ENV.findall(path.read_text(encoding="utf-8"))
    }
    full = (ROOT / ".env.full.example").read_text(encoding="utf-8")
    assert runtime_settings <= set(ENV.findall(full))


def test_web_manifest_matches_lockfile() -> None:
    manifest = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    locked = lockfile["packages"]["apps/web"]
    assert locked["dependencies"] == manifest["dependencies"]
    assert locked["devDependencies"] == manifest["devDependencies"]


def test_windows_launcher_starts_current_applications() -> None:
    launcher = (ROOT / "scripts/local.bat").read_text(encoding="utf-8").lower()
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    assert "*.bat text eol=crlf" in attributes
    assert re.search(r"\bcall\s+:", launcher) is None
    assert "-m alembic -c apps/api/alembic.ini upgrade head" in launcher
    assert "-m uvicorn app.main:app" in launcher
    assert "npm run dev --workspace @logan/web" in launcher
    assert "npm ci" in launcher
    assert r"node_modules\.bin\next.cmd" in launcher
    assert "npm ls --workspace @logan/web --depth=0" in launcher
    assert "get-nettcpconnection -state listen -localport 3000" in launcher
    assert "get-nettcpconnection -state listen -localport 8000" in launcher


def test_web_progress_panel_mirrors_pipeline_steps() -> None:
    pipeline = (ROOT / "apps/api/logan_analysis/pipeline.py").read_text(encoding="utf-8")
    panel = (
        ROOT / "apps/web/src/components/AnalysisProgressPanel.tsx"
    ).read_text(encoding="utf-8")

    step_names = set(re.findall(r'step_name="([a-z_]+)"', pipeline))
    step_names.update(re.findall(r'run_step\(\s*"([a-z_]+)"', pipeline))
    assert step_names, "pipeline step names not found"
    missing = [name for name in step_names if f'"{name}"' not in panel]
    assert missing == [], f"AnalysisProgressPanel is missing pipeline steps: {missing}"
