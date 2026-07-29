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
    assert "-m alembic -c apps/api/alembic.ini upgrade head" in launcher
    assert "-m uvicorn app.main:app" in launcher
    assert "npm run dev --workspace @logan/web" in launcher
    assert "npm ci" in launcher
    assert r"node_modules\.bin\next.cmd" in launcher
    assert "npm ls --workspace @logan/web --depth=0" in launcher
    assert "call :ensure_port_available 3000 web" in launcher
    assert "call :ensure_port_available 8000 api" in launcher
