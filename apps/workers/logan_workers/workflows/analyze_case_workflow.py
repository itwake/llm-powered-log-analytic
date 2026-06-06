from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy
except ImportError:

    @dataclass(frozen=True)
    class RetryPolicy:  # type: ignore[no-redef]
        maximum_attempts: int = 1

    class _WorkflowShim:
        @staticmethod
        def defn(target=None, **_kwargs):
            def decorate(value):
                return value

            return decorate(target) if target is not None else decorate

        @staticmethod
        def run(target=None, **_kwargs):
            def decorate(value):
                return value

            return decorate(target) if target is not None else decorate

        @staticmethod
        async def execute_activity(activity_name: str, params: Any, **_kwargs: Any) -> Any:
            from logan_workers.activities.analysis import run_analysis_pipeline_activity

            if activity_name != "run_analysis_pipeline_activity":
                raise ValueError(f"unknown local activity {activity_name}")
            return await run_analysis_pipeline_activity(params)

    workflow = _WorkflowShim()  # type: ignore[assignment]


@dataclass(frozen=True)
class AnalyzeCaseParams:
    case_id: str
    analysis_run_id: str
    paths: list[str]
    case_context: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    activity_start_to_close_seconds: int = 3600
    activity_max_attempts: int = 3


@dataclass(frozen=True)
class AnalyzeCaseResult:
    case_id: str
    analysis_run_id: str
    status: str
    templates: int
    causal_edges: int


@workflow.defn
class AnalyzeCaseWorkflow:
    """Replay-safe Temporal workflow for one analysis run."""

    @workflow.run
    async def run(self, params: AnalyzeCaseParams) -> AnalyzeCaseResult:
        return await workflow.execute_activity(
            "run_analysis_pipeline_activity",
            params,
            activity_id=f"{params.analysis_run_id}:run_analysis_pipeline",
            start_to_close_timeout=timedelta(
                seconds=params.activity_start_to_close_seconds
            ),
            retry_policy=RetryPolicy(maximum_attempts=params.activity_max_attempts),
        )
