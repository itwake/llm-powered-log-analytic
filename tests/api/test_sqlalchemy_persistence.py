from __future__ import annotations

from app.config import Settings
from app.sqlalchemy_store import SQLAlchemyStore


def test_core_records_persist_across_store_instances(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    settings = Settings(database_url=database_url)
    store = SQLAlchemyStore(app_settings=settings, database_url=database_url)
    user = store.register_user(
        email="owner@example.com",
        username="owner",
        full_name="Owner",
        external_id="subject-1",
    )
    case = store.create_case(user_id=user.id, data={"title": "Incident"})
    run = store.create_analysis_run(case_id=case.id, user_id=user.id, config={})

    recreated = SQLAlchemyStore(app_settings=settings, database_url=database_url)
    assert recreated.get_user_by_external_id("subject-1") == user
    persisted_case = recreated.get_case(case.id)
    assert persisted_case is not None
    assert persisted_case.title == case.title
    assert persisted_case.status == "analyzing"
    assert recreated.get_analysis_run(run.id) is not None
    assert len(recreated.list_analysis_runs(case.id)) == 1
