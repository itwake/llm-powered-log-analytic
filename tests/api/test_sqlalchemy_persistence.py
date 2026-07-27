from __future__ import annotations

import pytest

from app.config import Settings
from app.db import Base
from app.models import tables  # noqa: F401
from app.sqlalchemy_store import SQLAlchemyStore
from sqlalchemy.exc import IntegrityError


def test_database_contains_only_core_tables() -> None:
    assert set(Base.metadata.tables) == {
        "analysis_runs",
        "cases",
        "raw_files",
        "sessions",
        "users",
    }


def test_core_records_persist_across_store_instances(tmp_path) -> None:
    database_path = str(tmp_path / "logan.db")
    settings = Settings(database_path=database_path)
    store = SQLAlchemyStore(
        app_settings=settings,
        database_path=database_path,
        create_schema=True,
    )
    user = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name="Owner",
        external_id="subject-1",
    )
    case = store.create_case(user_id=user.id, data={"title": "Incident"})
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)

    recreated = SQLAlchemyStore(app_settings=settings, database_path=database_path)
    assert recreated.get_user_by_external_id("subject-1") == user
    persisted_case = recreated.get_case(case.id)
    assert persisted_case is not None
    assert persisted_case.title == case.title
    assert persisted_case.status == "analyzing"
    assert recreated.get_analysis_run(run.id) is not None
    assert len(recreated.list_analysis_runs(case.id)) == 1


def test_sqlite_enforces_foreign_keys() -> None:
    store = SQLAlchemyStore(
        app_settings=Settings(),
        database_path=":memory:",
        create_schema=True,
    )

    with pytest.raises(IntegrityError):
        store.create_case(user_id="missing-user", data={"title": "Incident"})


def test_only_the_run_owner_can_cancel() -> None:
    store = SQLAlchemyStore(
        app_settings=Settings(),
        database_path=":memory:",
        create_schema=True,
    )
    owner = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name=None,
    )
    other = store.register_user(
        email="other@example.com",
        username="other",
        full_name=None,
    )
    case = store.create_case(user_id=owner.id, data={"title": "Incident"})
    run = store.create_analysis_run(case_id=case.id, user_id=owner.id)

    with pytest.raises(KeyError):
        store.cancel_analysis_run(run_id=run.id, user_id=other.id)
