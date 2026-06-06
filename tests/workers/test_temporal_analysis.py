from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from logan_workers.activities import analysis as analysis_activity
from logan_workers.workflows import analyze_case_workflow
from logan_workers.workflows.analyze_case_workflow import (
    AnalyzeCaseParams,
    AnalyzeCaseResult,
    AnalyzeCaseWorkflow,
)

from app.config import Settings
from app.models import tables
from app.sqlalchemy_store import SQLAlchemyStore


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")


def _store(tmp_path: Path) -> tuple[SQLAlchemyStore, str, str]:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(database_url=database_url, store_backend="sqlalchemy")
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
