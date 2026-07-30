from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from logan_analysis.activities import ingestion
from logan_analysis.algorithms.multiline import merge_physical_lines
from logan_analysis.models import RawPhysicalLine
from logan_analysis.pipeline import AnalyzeCasePipeline

from tests.model_gateway_stub import StubModelGateway

FIXTURES = Path("tests/fixtures/logs/checkout_incident")


def _physical_line(index: int, text: str) -> RawPhysicalLine:
    return RawPhysicalLine(
        raw_line_id=f"raw-{index}",
        file_id="file-1",
        file_path="plain.log",
        line_number=index,
        raw_text=text,
        sha256=f"hash-{index}",
        ingestion_order=index,
    )


def test_plain_lines_remain_separate_while_stack_lines_are_merged() -> None:
    entries = merge_physical_lines(
        [
            _physical_line(1, "service started"),
            _physical_line(2, "request failed"),
            _physical_line(3, "    at handler.py:10"),
            _physical_line(4, "request recovered"),
        ]
    )

    assert [entry.line_numbers for entry in entries] == [[1], [2, 3], [4]]


def test_archive_expansion_uses_the_configured_limit(tmp_path) -> None:
    archive_path = tmp_path / "logs.zip"
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr("service.log", b"x" * 1024)
    assert archive_path.stat().st_size < 200

    with pytest.raises(ValueError, match="archive content exceeds"):
        ingestion.ingest_paths([archive_path], max_input_bytes=200)


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
