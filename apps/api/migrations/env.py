from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import URL, engine_from_config, pool
from sqlalchemy.engine import Connection

config = context.config
if config.config_file_name:
    # The API runs migrations in-process before serving, so this must configure the
    # Alembic loggers without switching off every logger that already exists -- the
    # default would permanently disable "logan.analysis" and drop analysis failure logs.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPOSITORY_ROOT / ".env")

from app.config import Settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import tables  # noqa: E402, F401

target_metadata = Base.metadata


def database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url").strip()
    if configured_url:
        return configured_url

    database_path = Path(Settings().database_path).expanduser()
    if not database_path.is_absolute():
        database_path = REPOSITORY_ROOT / database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return URL.create(
        "sqlite+pysqlite",
        database=str(database_path),
    ).render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    url = database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_with_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        run_with_connection(supplied_connection)
        return

    connectable = engine_from_config(
        {"sqlalchemy.url": database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        run_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
