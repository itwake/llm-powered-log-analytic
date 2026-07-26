from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ENV = re.compile(r"^\s*#?\s*(LOGAN_[A-Z0-9_]+)=", re.MULTILINE)


def test_relative_markdown_links_resolve() -> None:
    missing: list[str] = []
    files = [
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
    config = (ROOT / "apps/api/app/config.py").read_text(encoding="utf-8")
    full = (ROOT / ".env.full.example").read_text(encoding="utf-8")
    assert set(re.findall(r'"(LOGAN_[A-Z0-9_]+)"', config)) <= set(ENV.findall(full))


def test_repository_has_one_initial_schema() -> None:
    migrations = sorted((ROOT / "apps/api/migrations").glob("*.sql"))
    assert [path.name for path in migrations] == ["0001_initial.sql"]
    schema = migrations[0].read_text(encoding="utf-8")
    assert schema.count("CREATE TABLE ") == 6


def test_web_manifest_matches_lockfile() -> None:
    manifest = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    locked = lockfile["packages"]["apps/web"]
    assert locked["dependencies"] == manifest["dependencies"]
    assert locked["devDependencies"] == manifest["devDependencies"]
