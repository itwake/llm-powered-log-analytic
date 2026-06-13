from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app.config import Settings
from scripts.run_migrations import run_migrations


def test_run_migrations_skips_memory_store() -> None:
    result = run_migrations(Settings(store_backend="memory", database_url=None))

    assert result == {"status": "skipped", "reason": "memory_store"}


def test_run_migrations_creates_sqlalchemy_schema(tmp_path) -> None:
    database_path = tmp_path / "logan.db"
    database_url = f"sqlite:///{database_path}"

    result = run_migrations(Settings(store_backend="sqlalchemy", database_url=database_url))

    assert result == {"status": "migrated", "database_url_configured": True}
    engine = create_engine(database_url, future=True)
    try:
        assert "users" in inspect(engine).get_table_names()
        assert "analysis_runs" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_run_migrations_defaults_to_local_sqlite(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = run_migrations(Settings(store_backend="auto"))

    assert result == {"status": "migrated", "database_url_configured": True}
    database_path = tmp_path / ".logan" / "logan.db"
    assert database_path.exists()
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    try:
        assert "users" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
