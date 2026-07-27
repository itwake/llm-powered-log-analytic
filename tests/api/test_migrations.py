from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, inspect, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_TABLES = {
    "analysis_runs",
    "cases",
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
                "0001_initial"
            )

        command.check(config)
        command.downgrade(config, "base")
        assert not CORE_TABLES.intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()
