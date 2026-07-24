from __future__ import annotations

from typing import Any

from app.config import Settings, settings, validate_runtime_settings
from app.sqlalchemy_store import SQLAlchemyStore


def run_migrations(app_settings: Settings = settings) -> dict[str, Any]:
    validate_runtime_settings(app_settings)

    SQLAlchemyStore(
        app_settings=app_settings,
        database_url=app_settings.database_url,
        create_schema=True,
    )
    return {"status": "migrated", "database_url_configured": True}


def main() -> None:
    result = run_migrations()
    print(result["status"])


if __name__ == "__main__":
    main()
