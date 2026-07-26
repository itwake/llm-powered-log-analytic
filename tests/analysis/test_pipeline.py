from __future__ import annotations

from pathlib import Path

import pytest
from logan_analysis.pipeline import AnalyzeCasePipeline

from tests.model_gateway_stub import StubModelGateway

FIXTURES = Path("tests/fixtures/logs/checkout_incident")


@pytest.mark.asyncio
async def test_pipeline_without_llm_produces_deterministic_reports() -> None:
    result = await AnalyzeCasePipeline().run(
        case_id="case-1",
        analysis_run_id="run-1",
        paths=[str(path) for path in sorted(FIXTURES.glob("*.log"))],
    )

    assert len(result.files) == 3
    assert result.normalized_logs
    assert result.templates
    assert result.annotations == []
    assert result.progress["current_step"] == "completed"


@pytest.mark.asyncio
async def test_pipeline_uses_one_gateway_for_annotation_and_summary() -> None:
    gateway = StubModelGateway()
    result = await AnalyzeCasePipeline().run(
        case_id="case-1",
        analysis_run_id="run-1",
        paths=[str(path) for path in sorted(FIXTURES.glob("*.log"))],
        gateway=gateway,
    )

    assert result.annotations
    assert result.causal_graph.nodes
    assert result.causal_summary.evidence_refs
    assert result.progress["current_step"] == "completed"
    assert gateway.calls
