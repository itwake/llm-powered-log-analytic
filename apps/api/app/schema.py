
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, inspect

# Tables created by the first revision. A database that has these tables but no
# ``alembic_version`` predates Alembic and is stamped at that revision so later
# revisions still apply.
_CORE_TABLES = {
    "analysis_runs",
    "cases",
    "raw_files",
    "sessions",
    "users",
}
_LEGACY_SCHEMA_REVISION = "0001_initial"


def _stamp_legacy_current_schema(config: Config, database_path: str) -> None:
    if database_path == ":memory:" or not Path(database_path).expanduser().exists():
        return

    engine = create_engine(
        URL.create("sqlite+pysqlite", database=database_path),
        future=True,
    )
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    if "alembic_version" in table_names or not table_names.intersection(_CORE_TABLES):
        return
    if not _CORE_TABLES.issubset(table_names):
        existing = ", ".join(sorted(table_names.intersection(_CORE_TABLES)))
        missing = ", ".join(sorted(_CORE_TABLES - table_names))
        raise RuntimeError(
            "database contains an unversioned partial application schema; "
            f"existing tables: {existing}; missing tables: {missing}"
        )

    command.stamp(config, _LEGACY_SCHEMA_REVISION)


def upgrade_database(database_path: str) -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=database_path).render_as_string(
            hide_password=False
        ),
    )
    _stamp_legacy_current_schema(config, database_path)
    command.upgrade(config, "head")
