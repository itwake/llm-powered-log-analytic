from __future__ import annotations

import asyncio
from dataclasses import dataclass

from logan_workers.pipeline import AnalyzeCasePipeline


@dataclass(frozen=True)
class AnalyzeCaseParams:
    case_id: str
    analysis_run_id: str
    paths: list[str]


@dataclass(frozen=True)
class AnalyzeCaseResult:
    case_id: str
    analysis_run_id: str
    status: str
    templates: int
    causal_edges: int


class AnalyzeCaseWorkflow:
    """Temporal-compatible workflow placeholder.

    Later stages should replace this synchronous runner with Temporal SDK decorators and
    durable idempotent activities. The tested stage path uses the same orchestration order.
    """

    async def run(self, params: AnalyzeCaseParams) -> AnalyzeCaseResult:
        result = await AnalyzeCasePipeline().run(
            case_id=params.case_id,
            analysis_run_id=params.analysis_run_id,
            paths=params.paths,
        )
        return AnalyzeCaseResult(
            case_id=result.case_id,
            analysis_run_id=result.analysis_run_id,
            status="completed",
            templates=len(result.templates),
            causal_edges=len(result.causal_graph.edges),
        )


if __name__ == "__main__":
    asyncio.run(
        AnalyzeCaseWorkflow().run(
            AnalyzeCaseParams(case_id="local", analysis_run_id="local-run", paths=[])
        )
    )
