from __future__ import annotations

from app.config import Settings, settings
from app.records import (
    AnalysisRunCancelled,
    AnalysisRunRecord,
    CaseRecord,
    SessionRecord,
    UploadRecord,
    UserRecord,
    sanitize_error_message,
)
from app.sqlalchemy_store import SQLAlchemyStore

Store = SQLAlchemyStore


def create_ephemeral_store(app_settings: Settings = settings) -> Store:
    return Store(
        app_settings=app_settings,
        database_path=":memory:",
        create_schema=True,
    )


def create_store(app_settings: Settings = settings) -> Store:
    return Store(app_settings=app_settings, database_path=app_settings.database_path)


__all__ = [
    "AnalysisRunCancelled",
    "AnalysisRunRecord",
    "CaseRecord",
    "SessionRecord",
    "Store",
    "UploadRecord",
    "UserRecord",
    "create_ephemeral_store",
    "create_store",
    "sanitize_error_message",
]
