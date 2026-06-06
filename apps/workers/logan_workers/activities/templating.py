from __future__ import annotations

from logan_workers.algorithms.drain_adapter import StableDrainAdapter
from logan_workers.models import LogTemplate, NormalizedLogLine


def run_drain_templating(
    *,
    case_id: str,
    analysis_run_id: str,
    logs: list[NormalizedLogLine],
    config_hash: str = "default",
) -> tuple[list[NormalizedLogLine], list[LogTemplate]]:
    adapter = StableDrainAdapter(config_hash=config_hash)
    return adapter.cluster(case_id=case_id, analysis_run_id=analysis_run_id, logs=logs)
