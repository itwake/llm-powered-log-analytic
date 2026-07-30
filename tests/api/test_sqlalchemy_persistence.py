from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import sqlalchemy_store
from app.config import Settings
from app.db import Base
from app.models import tables  # noqa: F401
from app.services import analysis_result_artifacts
from app.services.analysis_result_artifacts import read_artifact
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
async def test_completed_result_uses_segmented_redacted_artifacts(
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
    assert payload["format"] == "logan.analysis-result-manifest"
    summary_raw = read_artifact(payload["sections"]["summary"], settings=store.settings)
    logs_raw = read_artifact(payload["logs"]["chunks"][0], settings=store.settings)
    persisted_summary = json.loads(summary_raw)
    persisted_logs = json.loads(logs_raw)
    assert "raw-secret" not in summary_raw.decode("utf-8")
    assert "raw-secret" not in logs_raw.decode("utf-8")
    assert persisted_summary["files"][0]["lines"] == []
    assert "message" not in persisted_logs[0]
    assert payload["logs"]["total"] == 1

    store._clear_analysis_result_cache()
    result = store.get_analysis_result(case.id, run.id)
    assert result is not None
    assert result.normalized_logs[0].redacted_message.endswith(
        "password=<SECRET> failed"
    )
    assert result.raw_entries == []
    assert result.files[0].lines == []

    store._clear_analysis_result_cache()

    def unexpected_decode(payload):  # noqa: ANN001
        raise AssertionError("run metadata must not decode the result")

    monkeypatch.setattr(sqlalchemy_store, "_decode_analysis_result", unexpected_decode)
    assert store.get_analysis_run(run.id).status == "completed"
    assert store.list_analysis_runs(case.id)[0].status == "completed"


@pytest.mark.asyncio
async def test_legacy_completed_result_is_cached_across_report_reads(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user, case, path = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)
    await store.run_analysis(
        run_id=run.id,
        user_id=user.id,
        file_paths=[path],
    )
    completed_result = store.get_analysis_result(case.id, run.id)
    assert completed_result is not None
    with store._session() as session:
        row = session.get(tables.AnalysisRun, run.id)
        row.result_json = sqlalchemy_store._encode_analysis_result(completed_result)

    original_decode = sqlalchemy_store._decode_analysis_result
    decode_calls = 0

    def counting_decode(payload):  # noqa: ANN001
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(payload)

    monkeypatch.setattr(sqlalchemy_store, "_decode_analysis_result", counting_decode)

    store._clear_analysis_result_cache()
    first_read = store.get_analysis_result(case.id, run.id)
    second_read = store.get_analysis_result(case.id, run.id)

    assert first_read is second_read
    assert decode_calls == 1


@pytest.mark.asyncio
async def test_finalization_failure_marks_the_run_and_case_failed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user, case, path = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)

    def fail_encoding(result, *, settings):  # noqa: ANN001
        raise RuntimeError("result persistence failed")

    monkeypatch.setattr(
        sqlalchemy_store,
        "write_analysis_result_manifest",
        fail_encoding,
    )
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
    assert failed.progress["failed_step"] == "finalizing"
    assert failed.progress["error_type"] == "RuntimeError"
    assert "error_code" not in failed.progress
    assert failed.error_message == "result persistence failed"
    assert store.get_case(case.id).status == "failed"


@pytest.mark.asyncio
async def test_file_not_found_finalization_records_safe_diagnostics(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user, case, path = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)

    def fail_encoding(result, *, settings):  # noqa: ANN001
        raise FileNotFoundError(
            2,
            "No such file or directory",
            r"C:\customer-data\incident-secret.log",
        )

    monkeypatch.setattr(
        sqlalchemy_store,
        "write_analysis_result_manifest",
        fail_encoding,
    )
    with pytest.raises(FileNotFoundError):
        await store.run_analysis(
            run_id=run.id,
            user_id=user.id,
            file_paths=[path],
        )

    failed = store.get_analysis_run(run.id)
    assert failed is not None
    assert failed.progress["current_step"] == "failed"
    assert failed.progress["failed_step"] == "finalizing"
    assert failed.progress["error_type"] == "FileNotFoundError"
    assert failed.progress["error_code"] == 2
    assert "customer-data" not in failed.error_message
    assert "incident-secret.log" not in failed.error_message


@pytest.mark.asyncio
async def test_finalization_is_visible_and_does_not_block_status_reads(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user, case, path = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)
    entered = threading.Event()
    release = threading.Event()
    original_encode = sqlalchemy_store.write_analysis_result_manifest

    def blocking_encode(result, *, settings):  # noqa: ANN001
        entered.set()
        release.wait(timeout=2)
        return original_encode(result, settings=settings)

    monkeypatch.setattr(
        sqlalchemy_store,
        "write_analysis_result_manifest",
        blocking_encode,
    )
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


@pytest.mark.asyncio
async def test_segmented_logs_read_only_the_page_chunks(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_result_artifacts, "RESULT_LOG_CHUNK_SIZE", 2)
    store, user, case, path = _analysis_fixture(tmp_path)
    Path(path).write_text(
        "\n".join(
            f"2026-01-01T00:00:0{index}Z ERROR api request {index} failed"
            for index in range(5)
        )
        + "\n",
        encoding="utf-8",
    )
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)
    await store.run_analysis(run_id=run.id, user_id=user.id, file_paths=[path])

    with store.session_factory() as session:
        manifest = session.get(tables.AnalysisRun, run.id).result_json
    assert [chunk["record_count"] for chunk in manifest["logs"]["chunks"]] == [2, 2, 1]

    original_read = sqlalchemy_store.read_log_chunk
    chunk_reads = 0

    def counting_read(entry, *, settings):  # noqa: ANN001
        nonlocal chunk_reads
        chunk_reads += 1
        return original_read(entry, settings=settings)

    monkeypatch.setattr(sqlalchemy_store, "read_log_chunk", counting_read)
    page = store.get_analysis_logs_page(case.id, run.id, offset=2, limit=2)

    assert page is not None
    assert page.total == 5
    assert [row.line_number for row in page.rows] == [3, 4]
    assert chunk_reads == 1

    filtered = store.get_analysis_logs_page(
        case.id,
        run.id,
        q="request 4",
        limit=2,
    )
    assert filtered is not None
    assert filtered.total == 1
    assert [row.line_number for row in filtered.rows] == [5]
    assert filtered.facets == {
        "service": {"unknown": 1},
        "golden_signal": {"error": 1},
        "fault_category": {},
    }


def test_interrupted_runs_are_failed_on_startup_reconciliation(tmp_path) -> None:
    store, user, case, _ = _analysis_fixture(tmp_path)
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)

    assert store.fail_interrupted_analysis_runs() == 1

    failed = store.get_analysis_run(run.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "analysis was interrupted by an API restart"
    assert store.get_case(case.id).status == "failed"


@pytest.mark.asyncio
async def test_filtered_logs_via_search_index_match_brute_force(tmp_path) -> None:
    database_path = str(tmp_path / "logan.db")
    settings = Settings(
        database_path=database_path,
        local_object_store_dir=str(tmp_path / "objects"),
    )
    store = SQLAlchemyStore(
        app_settings=settings,
        database_path=database_path,
        create_schema=True,
    )
    user = store.register_user(email="o@example.com", username="o", full_name=None)
    case = store.create_case(user_id=user.id, data={"title": "Incident"})
    path = tmp_path / "mixed.log"
    lines = [
        "2026-01-01T00:00:00Z ERROR payment-service connection refused id=alpha",
        "2026-01-01T00:01:00Z ERROR payment-service timeout while calling ledger",
        "2026-01-01T00:02:00Z WARN auth-service token cache miss for alpha",
        "2026-01-01T00:03:00Z ERROR payment-service connection refused id=beta",
        "no timestamp on this line at all",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run = store.create_analysis_run(case_id=case.id, user_id=user.id)
    await store.run_analysis(run_id=run.id, user_id=user.id, file_paths=[str(path)])

    manifest_index = sqlalchemy_store.load_search_index(
        store._get_analysis_result_payload(case.id, run.id),
        settings=settings,
    )
    assert manifest_index is not None, "new manifests must carry a search index"

    # The trailing headerless line merges into the previous entry as a
    # continuation, so five physical lines produce four entries.
    everything = store.get_analysis_logs_page(case.id, run.id, limit=100)
    assert everything.total == 4
    assert everything.rows[-1].line_numbers == [4, 5]

    searched = store.get_analysis_logs_page(case.id, run.id, q="connection refused")
    assert searched.total == 2
    assert all("connection refused" in row.redacted_message for row in searched.rows)
    assert searched.facets["service"] == {"payment-service": 2}

    windowed = store.get_analysis_logs_page(
        case.id,
        run.id,
        window_start=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
    )
    assert windowed.total == 2
    assert {row.line_number for row in windowed.rows} == {2, 3}

    by_service = store.get_analysis_logs_page(case.id, run.id, service="auth-service")
    assert by_service.total == 1
    assert by_service.rows[0].line_number == 3

    template_id = searched.rows[0].template_id
    assert template_id is not None
    by_template = store.get_analysis_logs_page(case.id, run.id, template_id=template_id)
    assert by_template.total == 2
    assert {row.line_number for row in by_template.rows} == {1, 4}

    combined = store.get_analysis_logs_page(
        case.id,
        run.id,
        q="connection refused",
        window_start=datetime(2026, 1, 1, 0, 2, 30, tzinfo=UTC),
    )
    assert combined.total == 1
    assert combined.rows[0].line_number == 4

    missing = store.get_analysis_logs_page(case.id, run.id, q="zzz-not-there")
    assert missing.total == 0
    assert missing.rows == []
