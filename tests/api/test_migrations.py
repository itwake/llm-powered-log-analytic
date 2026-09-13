from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, inspect, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_TABLES = {
    "analysis_runs",
    "cases",
    "llm_providers",
    "raw_files",
    "sessions",
    "users",
}


def migration_config(database_path: Path) -> Config:
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create(
            "sqlite+pysqlite",
            database=str(database_path),
        ).render_as_string(hide_password=False),
    )
    return config


def test_migrations_create_current_schema_and_downgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "logan.db"
    config = migration_config(database_path)

    command.upgrade(config, "head")

    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        future=True,
    )
    try:
        assert set(inspect(engine).get_table_names()) == CORE_TABLES | {"alembic_version"}
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0002_llm_providers"
            )

        command.check(config)
        command.downgrade(config, "base")
        assert not CORE_TABLES.intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_a_missing_database_directory(tmp_path: Path) -> None:
    """A fresh checkout has no data directory, and SQLite will not create one."""
    from app.schema import upgrade_database

    database_path = tmp_path / "nested" / "data" / "logan.db"
    assert not database_path.parent.exists()

    upgrade_database(str(database_path))

    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        future=True,
    )
    try:
        assert CORE_TABLES.issubset(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migrations_do_not_disable_application_loggers(tmp_path: Path) -> None:
    """The API runs migrations in-process, so Alembic must not switch its loggers off."""
    import logging

    from app.schema import upgrade_database

    logger = logging.getLogger("logan.analysis")
    logger.disabled = False

    upgrade_database(str(tmp_path / "logan.db"))

    assert not logger.disabled
