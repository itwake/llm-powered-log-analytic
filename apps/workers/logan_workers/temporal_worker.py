from __future__ import annotations

import asyncio

from logan_workers.activities.analysis import run_analysis_pipeline_activity
from logan_workers.temporal_client import TemporalUnavailableError
from logan_workers.workflows.analyze_case_workflow import AnalyzeCaseWorkflow


async def main() -> None:
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
    except ImportError as exc:
        raise TemporalUnavailableError(
            "Temporal SDK is not installed. Install temporalio to run the Logan worker."
        ) from exc

    from app.config import Settings

    app_settings = Settings()
    try:
        client = await Client.connect(
            app_settings.temporal_address,
            namespace=app_settings.temporal_namespace,
        )
    except Exception as exc:
        raise TemporalUnavailableError(
            "Unable to connect to Temporal at "
            f"{app_settings.temporal_address} in namespace "
            f"{app_settings.temporal_namespace}."
        ) from exc

    worker = Worker(
        client,
        task_queue=app_settings.temporal_task_queue,
        workflows=[AnalyzeCaseWorkflow],
        activities=[run_analysis_pipeline_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
