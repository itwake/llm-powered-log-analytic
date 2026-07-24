from __future__ import annotations

from collections.abc import Callable
from typing import Any

from logan_workers.models import AnalysisResult
from logan_workers.pipeline import AnalyzeCasePipeline
from logan_workers.workflows.analyze_case_workflow import (
    AnalyzeCaseParams,
    AnalyzeCaseResult,
)

try:
    from temporalio import activity
except ImportError:

    class _ActivityShim:
        @staticmethod
        def defn(target=None, **_kwargs):
            def decorate(value):
                return value

            return decorate(target) if target is not None else decorate

    activity = _ActivityShim()  # type: ignore[assignment]


def create_sqlalchemy_activity_store() -> Any:
    from app.config import Settings
    from app.sqlalchemy_store import SQLAlchemyStore

    app_settings = Settings()
    if not app_settings.database_url:
        raise RuntimeError(
            "LOGAN_DATABASE_URL is required for Temporal analysis activities"
        )
    return SQLAlchemyStore(
        app_settings=app_settings,
        database_url=app_settings.database_url,
    )


STORE_FACTORY: Callable[[], Any] = create_sqlalchemy_activity_store
S3_CLIENT_FACTORY: Callable[[Any], Any] | None = None


def _result_summary(result: AnalysisResult, *, status: str = "completed") -> AnalyzeCaseResult:
    return AnalyzeCaseResult(
        case_id=result.case_id,
        analysis_run_id=result.analysis_run_id,
        status=status,
        templates=len(result.templates),
        causal_edges=len(result.causal_graph.edges),
    )


def _user_id_for_completion(params: AnalyzeCaseParams, run: Any, case: Any) -> str:
    context_user_id = params.case_context.get("user_id")
    if isinstance(context_user_id, str) and context_user_id:
        return context_user_id
    if getattr(run, "created_by", None):
        return str(run.created_by)
    return str(case.created_by)


@activity.defn(name="run_analysis_pipeline_activity")
async def run_analysis_pipeline_activity(params: AnalyzeCaseParams) -> AnalyzeCaseResult:
    from app.config import Settings
    from app.services.analysis_inputs import (
        analysis_input_backend_counts,
        materialize_analysis_inputs,
    )
    from app.store import merge_recorded_progress

    store = STORE_FACTORY()
    run = store.get_analysis_run(params.analysis_run_id)
    if run is None:
        raise KeyError(params.analysis_run_id)
    if run.case_id != params.case_id:
        raise ValueError("analysis run does not belong to requested case")
    case = store.get_case(params.case_id)
    if case is None:
        raise KeyError(params.case_id)

    user_id = _user_id_for_completion(params, run, case)

    def record_progress(event: dict[str, Any]) -> None:
        store.apply_analysis_job_event(run_id=params.analysis_run_id, event=event)

    try:
        existing_result = store.get_analysis_result(params.case_id, params.analysis_run_id)
        if existing_result is not None:
            if run.status == "completed":
                return _result_summary(existing_result, status=run.status)
            completed_run = store.complete_analysis_run(
                run_id=params.analysis_run_id,
                result=existing_result,
                user_id=user_id,
            )
            return _result_summary(existing_result, status=completed_run.status)

        app_settings = getattr(store, "settings", None) or Settings()
        from app.services.model_gateway_factory import create_model_gateway

        gateway = create_model_gateway(app_settings)
        with materialize_analysis_inputs(
            params.paths,
            app_settings,
            run_id=params.analysis_run_id,
            s3_client_factory=S3_CLIENT_FACTORY,
        ) as materialized_paths:
            record_progress(
                {
                    "step_name": "materialize_inputs",
                    "event_type": "completed",
                    "status": "completed",
                    "attempt": 1,
                    "idempotency_key": "materialize_inputs:attempt:1",
                    "metadata": {
                        "source_count": len(params.paths),
                        "materialized_count": len(materialized_paths),
                        "storage_backend_counts": analysis_input_backend_counts(params.paths),
                    },
                }
            )
            result = await AnalyzeCasePipeline().run(
                case_id=params.case_id,
                analysis_run_id=params.analysis_run_id,
                paths=materialized_paths,
                case_context=params.case_context,
                config=params.config,
                gateway=gateway,
                progress_callback=record_progress,
            )
        recorded_run = store.get_analysis_run(params.analysis_run_id)
        result = result.model_copy(
            update={
                "progress": merge_recorded_progress(
                    result.progress,
                    recorded_run.progress if recorded_run else None,
                )
            }
        )
        completed_run = store.complete_analysis_run(
            run_id=params.analysis_run_id,
            result=result,
            user_id=user_id,
        )
        return _result_summary(result, status=completed_run.status)
    except Exception as exc:
        from app.store import sanitize_error_message

        store.fail_analysis_run(
            run_id=params.analysis_run_id,
            error_message=sanitize_error_message(exc),
            user_id=user_id,
        )
        raise
