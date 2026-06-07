from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models import tables
from app.sqlalchemy_store import SQLAlchemyStore
from logan_workers.activities import analysis as analysis_activity
from logan_workers.workflows.analyze_case_workflow import (
    AnalyzeCaseParams,
    AnalyzeCaseWorkflow,
)


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")


def _store(tmp_path: Path) -> tuple[SQLAlchemyStore, str, str, str]:
    database_url = f"sqlite:///{tmp_path / 'logan-temporal-integration.db'}"
    app_settings = Settings(database_url=database_url, store_backend="sqlalchemy")
    store = SQLAlchemyStore(app_settings=app_settings, database_url=database_url)
    user = store.register_user(
        email="temporal-integration@example.com",
        username="temporal-integration",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Temporal retry checkout incident",
            "issue_description": "Customers report intermittent checkout failures.",
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
    return store, user.id, case.id, run.id


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_temporal_retries_logan_activity_and_activity_remains_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.getenv("LOGAN_RUN_TEMPORAL_INTEGRATION") != "true":
        pytest.skip("set LOGAN_RUN_TEMPORAL_INTEGRATION=true to run the Temporal test server")

    testing = pytest.importorskip("temporalio.testing")
    from temporalio import activity
    from temporalio.worker import Worker

    store, user_id, case_id, run_id = _store(tmp_path)
    monkeypatch.setattr(analysis_activity, "STORE_FACTORY", lambda: store)
    monkeypatch.setattr(analysis_activity, "S3_CLIENT_FACTORY", None)

    attempts = {"count": 0}

    @activity.defn(name="run_analysis_pipeline_activity")
    async def flaky_then_real_logan_activity(params: AnalyzeCaseParams) -> Any:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("intentional Temporal retry smoke failure")
        return await analysis_activity.run_analysis_pipeline_activity(params)

    params = AnalyzeCaseParams(
        case_id=case_id,
        analysis_run_id=run_id,
        paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
        case_context={
            "title": "Temporal retry checkout incident",
            "product": "commerce-platform",
            "user_id": user_id,
        },
        config={"default_window_size_seconds": 60},
        activity_start_to_close_seconds=30,
        activity_max_attempts=2,
    )

    env = await testing.WorkflowEnvironment.start_time_skipping()
    async with env:
        task_queue = f"logan-temporal-retry-{run_id}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[AnalyzeCaseWorkflow],
            activities=[flaky_then_real_logan_activity],
        ):
            result = await env.client.execute_workflow(
                AnalyzeCaseWorkflow.run,
                params,
                id=f"logan-temporal-retry-{run_id}",
                task_queue=task_queue,
            )

    assert attempts["count"] == 2
    assert result.status == "completed"
    assert result.templates > 0
    assert result.causal_edges > 0
    run = store.get_analysis_run(run_id)
    assert run is not None
    assert run.status == "completed"
    counts = _fanout_counts(store, run_id)
    assert counts["raw_files"] > 0
    assert counts["raw_log_lines"] > 0
    assert counts["normalized_log_lines"] > 0
    assert counts["log_templates"] == result.templates
    assert counts["causal_edges"] == result.causal_edges
    event_count = len(store.list_job_events(case_id=case_id, analysis_run_id=run_id))

    second = await analysis_activity.run_analysis_pipeline_activity(params)

    assert second == result
    assert _fanout_counts(store, run_id) == counts
    assert len(store.list_job_events(case_id=case_id, analysis_run_id=run_id)) == event_count
