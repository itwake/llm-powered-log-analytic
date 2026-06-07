from __future__ import annotations

from typing import Any

from logan_workers.algorithms.drain_adapter import build_drain_adapter
from logan_workers.models import LogTemplate, NormalizedLogLine


def run_drain_templating(
    *,
    case_id: str,
    analysis_run_id: str,
    logs: list[NormalizedLogLine],
    config_hash: str = "default",
    config: dict[str, Any] | None = None,
) -> tuple[list[NormalizedLogLine], list[LogTemplate]]:
    adapter = build_drain_adapter(config_hash=config_hash, config=config)
    return adapter.cluster(case_id=case_id, analysis_run_id=analysis_run_id, logs=logs)
