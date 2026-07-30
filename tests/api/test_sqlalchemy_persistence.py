from __future__ import annotations

import asyncio
import base64
import json
import threading
import zlib

import pytest

from app import sqlalchemy_store
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


def test_terminal_run_progress_cannot_be_overwritten() -> None:
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
    case = store.create_case(user_id=owner.id, data={"title": "Incident"})
    run = store.create_analysis_run(case_id=case.id, user_id=owner.id)
    store.cancel_analysis_run(run_id=run.id, user_id=owner.id)

    store.update_analysis_progress(
        run_id=run.id,
        progress={"current_step": "causal_summary", "steps": {}},
    )

    cancelled = store.get_analysis_run(run.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.progress["current_step"] == "cancelled"


def _analysis_fixture(
    tmp_path,
) -> tuple[SQLAlchemyStore, object, object, str]:
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
        full_name=None,
    )
    case = store.create_case(user_id=user.id, data={"title": "Incident"})
    path = tmp_path / "incident.log"
    path.write_text(
        "2026-01-01T00:00:00Z ERROR api password=raw-secret failed\n",
        encoding="utf-8",
    )
    return store, user, case, str(path)


@pytest.mark.asyncio
async def test_completed_result_uses_a_compact_redacted_envelope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user, case, path = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)

    completed = await store.run_analysis(
        run_id=run.id,
        user_id=user.id,
        file_paths=[path],
    )

    assert completed.status == "completed"
    with store.session_factory() as session:
        payload = session.get(tables.AnalysisRun, run.id).result_json
    assert payload["format"] == "logan.analysis-result"
    raw = zlib.decompress(base64.b64decode(payload["payload"]))
    persisted = json.loads(raw)
    assert "raw-secret" not in raw.decode("utf-8")
    assert "raw_entries" not in persisted
    assert "lines" not in persisted["files"][0]
    assert "message" not in persisted["normalized_logs"][0]

    result = store.get_analysis_result(case.id, run.id)
    assert result is not None
    assert result.normalized_logs[0].redacted_message.endswith(
        "password=<SECRET> failed"
    )
    assert result.raw_entries == []
    assert result.files[0].lines == []

    def unexpected_decode(payload):  # noqa: ANN001
        raise AssertionError("run metadata must not decode the result")

    monkeypatch.setattr(sqlalchemy_store, "_decode_analysis_result", unexpected_decode)
    assert store.get_analysis_run(run.id).status == "completed"
    assert store.list_analysis_runs(case.id)[0].status == "completed"


@pytest.mark.asyncio
async def test_finalization_failure_marks_the_run_and_case_failed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user, case, path = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)

    def fail_encoding(result):  # noqa: ANN001
        raise RuntimeError("result persistence failed")

    monkeypatch.setattr(sqlalchemy_store, "_encode_analysis_result", fail_encoding)
    with pytest.raises(RuntimeError, match="result persistence failed"):
        await store.run_analysis(
            run_id=run.id,
            user_id=user.id,
            file_paths=[path],
        )

    failed = store.get_analysis_run(run.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.progress["current_step"] == "failed"
    assert failed.error_message == "result persistence failed"
    assert store.get_case(case.id).status == "failed"


@pytest.mark.asyncio
async def test_finalization_is_visible_and_does_not_block_status_reads(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user, case, path = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)
    entered = threading.Event()
    release = threading.Event()
    original_encode = sqlalchemy_store._encode_analysis_result

    def blocking_encode(result):  # noqa: ANN001
        entered.set()
        release.wait(timeout=2)
        return original_encode(result)

    monkeypatch.setattr(sqlalchemy_store, "_encode_analysis_result", blocking_encode)
    task = asyncio.create_task(
        store.run_analysis(
            run_id=run.id,
            user_id=user.id,
            file_paths=[path],
        )
    )
    assert await asyncio.to_thread(entered.wait, 1)

    finalizing = await asyncio.wait_for(
        asyncio.to_thread(store.get_analysis_run, run.id),
        timeout=0.5,
    )
    assert finalizing is not None
    assert finalizing.status == "processing"
    assert finalizing.progress["current_step"] == "finalizing"

    release.set()
    assert (await task).status == "completed"


def test_interrupted_runs_are_failed_on_startup_reconciliation(tmp_path) -> None:
    store, user, case, _ = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)

    assert store.fail_interrupted_analysis_runs() == 1

    failed = store.get_analysis_run(run.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "analysis was interrupted by an API restart"
    assert store.get_case(case.id).status == "failed"
