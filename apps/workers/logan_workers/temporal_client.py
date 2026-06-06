from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from logan_workers.workflows.analyze_case_workflow import (
    AnalyzeCaseParams,
    AnalyzeCaseWorkflow,
)


class TemporalUnavailableError(RuntimeError):
    """Raised when the Temporal SDK or service is unavailable."""


@dataclass(frozen=True)
class TemporalClientConfig:
    address: str = "temporal:7233"
    namespace: str = "default"
    task_queue: str = "logan-analysis"


async def start_analyze_case_workflow(
    *,
    case_id: str,
    analysis_run_id: str,
    paths: list[str],
    case_context: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    temporal_config: TemporalClientConfig | None = None,
    workflow_id: str | None = None,
) -> Any:
    temporal_config = temporal_config or TemporalClientConfig()
    try:
        from temporalio.client import Client
    except ImportError as exc:
        raise TemporalUnavailableError(
            "Temporal SDK is not installed. Install temporalio to use "
            "LOGAN_ANALYSIS_ORCHESTRATOR=temporal."
        ) from exc

    try:
        client = await Client.connect(
            temporal_config.address,
            namespace=temporal_config.namespace,
        )
    except Exception as exc:
        raise TemporalUnavailableError(
            "Unable to connect to Temporal at "
            f"{temporal_config.address} in namespace {temporal_config.namespace}."
        ) from exc

    params = AnalyzeCaseParams(
        case_id=case_id,
        analysis_run_id=analysis_run_id,
        paths=paths,
        case_context=case_context or {},
        config=config or {},
    )
    try:
        return await client.start_workflow(
            AnalyzeCaseWorkflow.run,
            params,
            id=workflow_id or f"analyze-case-{analysis_run_id}",
            task_queue=temporal_config.task_queue,
        )
    except Exception as exc:
        raise TemporalUnavailableError(
            "Unable to start AnalyzeCaseWorkflow on Temporal task queue "
            f"{temporal_config.task_queue}."
        ) from exc
