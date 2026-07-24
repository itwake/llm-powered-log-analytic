from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.models import tables
from app.sqlalchemy_store import SQLAlchemyStore
from logan_workers.activities import analysis as analysis_activity
from logan_workers.workflows import analyze_case_workflow
from logan_workers.workflows.analyze_case_workflow import (
    AnalyzeCaseParams,
    AnalyzeCaseResult,
    AnalyzeCaseWorkflow,
)
from sqlalchemy import func, select

FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.download_calls: list[dict[str, str]] = []

    def download_file(self, *, Bucket: str, Key: str, Filename: str) -> None:
        self.download_calls.append({"Bucket": Bucket, "Key": Key, "Filename": Filename})
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])


def _store(tmp_path: Path) -> tuple[SQLAlchemyStore, str, str]:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        llm_provider="mock",
    )
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="temporal-worker@example.com",
        username="temporal-worker",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Checkout API intermittent 500 errors",
            "issue_description": "Customers report intermittent 500 during checkout.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "production",
            "incident_start": datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
            "incident_end": datetime(2026, 6, 6, 11, 0, tzinfo=UTC),
            "timezone": "UTC",
        },
    )
    run = store._create_analysis_run(
        case_id=case.id,
        user_id=user.id,
        config={"default_window_size_seconds": 60},
    )
    return store, case.id, run.id


def _fanout_counts(store: SQLAlchemyStore, run_id: str) -> dict[str, int]:
    with store.session_factory() as session:
        return {
            "raw_files": session.scalar(
                select(func.count()).select_from(tables.RawFile).where(
                    tables.RawFile.analysis_run_id == run_id
                )
            )
            or 0,
            "raw_log_lines": session.scalar(
                select(func.count()).select_from(tables.RawLogLine).where(
                    tables.RawLogLine.analysis_run_id == run_id
                )
            )
            or 0,
            "normalized_log_lines": session.scalar(
                select(func.count()).select_from(tables.NormalizedLogLine).where(
                    tables.NormalizedLogLine.analysis_run_id == run_id
                )
            )
            or 0,
            "log_templates": session.scalar(
                select(func.count()).select_from(tables.LogTemplate).where(
                    tables.LogTemplate.analysis_run_id == run_id
                )
            )
            or 0,
            "causal_edges": session.scalar(
                select(func.count()).select_from(tables.CausalEdge).where(
                    tables.CausalEdge.analysis_run_id == run_id
                )
            )
            or 0,
        }


@pytest.mark.asyncio
async def test_workflow_executes_activity_with_stable_retry_options(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    expected = AnalyzeCaseResult(
        case_id="case-1",
        analysis_run_id="run-1",
        status="completed",
        templates=2,
        causal_edges=1,
    )

    class FakeWorkflow:
        async def execute_activity(self, activity_name: str, params: Any, **kwargs: Any) -> Any:
            calls.append({"activity_name": activity_name, "params": params, **kwargs})
            return expected

    monkeypatch.setattr(analyze_case_workflow, "workflow", FakeWorkflow())
    params = AnalyzeCaseParams(
        case_id="case-1",
        analysis_run_id="run-1",
        paths=["/tmp/safe.log"],
        case_context={"title": "Checkout"},
        config={"default_window_size_seconds": 60},
        activity_start_to_close_seconds=42,
        activity_max_attempts=5,
    )

    result = await AnalyzeCaseWorkflow().run(params)

    assert result == expected
    assert len(calls) == 1
    call = calls[0]
    assert call["activity_name"] == "run_analysis_pipeline_activity"
    assert call["params"] == params
    assert call["activity_id"] == "run-1:run_analysis_pipeline"
    assert call["start_to_close_timeout"] == timedelta(seconds=42)
    assert call["retry_policy"].maximum_attempts == 5


@pytest.mark.asyncio
async def test_analysis_activity_persists_completion_and_is_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, case_id, run_id = _store(tmp_path)
    monkeypatch.setattr(analysis_activity, "STORE_FACTORY", lambda: store)
    params = AnalyzeCaseParams(
        case_id=case_id,
        analysis_run_id=run_id,
        paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
        case_context={
            "title": "Checkout API intermittent 500 errors",
            "product": "commerce-platform",
        },
        config={"default_window_size_seconds": 60},
    )

    first = await analysis_activity.run_analysis_pipeline_activity(params)

    run = store.get_analysis_run(run_id)
    assert run is not None
    assert run.status == "completed"
    assert first.status == "completed"
    assert first.templates > 0
    assert first.causal_edges > 0
    events = store.list_job_events(case_id=case_id, analysis_run_id=run_id)
    assert len(events) >= 22
    assert {event.step_name for event in events} >= {"ingest_paths", "export_artifacts"}
    counts = _fanout_counts(store, run_id)
    assert counts["raw_files"] > 0
    assert counts["raw_log_lines"] > 0
    assert counts["normalized_log_lines"] > 0
    assert counts["log_templates"] == first.templates
    assert counts["causal_edges"] == first.causal_edges

    second = await analysis_activity.run_analysis_pipeline_activity(params)

    assert second == first
    assert len(store.list_job_events(case_id=case_id, analysis_run_id=run_id)) == len(events)
    assert _fanout_counts(store, run_id) == counts


@pytest.mark.asyncio
async def test_analysis_activity_materializes_s3_inputs_in_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        llm_provider="mock",
        object_store_backend="s3",
        analysis_input_tmp_dir=str(tmp_path / "analysis-inputs"),
        s3_bucket="logan",
        s3_access_key="access",
        s3_secret_key="secret",
    )
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="temporal-s3@example.com",
        username="temporal-s3",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Temporal S3 analysis",
            "issue_description": "Worker should materialize S3 inputs.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "production",
            "timezone": "UTC",
        },
    )
    run = store._create_analysis_run(
        case_id=case.id,
        user_id=user.id,
        config={"default_window_size_seconds": 60},
    )
    fake_s3 = FakeS3Client()
    key = "cases/case-1/uploads/file-1/gateway.log"
    fake_s3.objects[("logan", key)] = (
        b"2026-06-06T10:00:00Z ERROR gateway-service failed checkout request\n"
    )
    monkeypatch.setattr(analysis_activity, "STORE_FACTORY", lambda: store)
    monkeypatch.setattr(analysis_activity, "S3_CLIENT_FACTORY", lambda _: fake_s3)
    params = AnalyzeCaseParams(
        case_id=case.id,
        analysis_run_id=run.id,
        paths=[f"s3://logan/{key}"],
        case_context={"title": "Temporal S3 analysis", "user_id": user.id},
        config={"default_window_size_seconds": 60},
    )

    result = await analysis_activity.run_analysis_pipeline_activity(params)

    assert result.status == "completed"
    assert _fanout_counts(store, run.id)["raw_files"] == 1
    assert fake_s3.download_calls
    assert not Path(fake_s3.download_calls[0]["Filename"]).exists()
    materialize_events = store.list_job_events(
        analysis_run_id=run.id,
        step_name="materialize_inputs",
    )
    assert [event.metadata for event in materialize_events] == [
        {
            "source_count": 1,
            "materialized_count": 1,
            "storage_backend_counts": {"s3": 1},
        }
    ]
