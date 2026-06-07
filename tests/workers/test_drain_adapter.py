from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from logan_workers.algorithms.drain_adapter import (
    Drain3Adapter,
    DrainConfig,
    StableDrainAdapter,
    build_drain_adapter,
)
from logan_workers.activities.broadcasting import broadcast_annotations
from logan_workers.activities.sampling import select_samples
from logan_workers.models import NormalizedLogLine, TemplateAnnotation


def _line(index: int, message: str, *, service: str = "api") -> NormalizedLogLine:
    return NormalizedLogLine(
        log_id=f"log-{index}",
        raw_log_id=f"raw-{index}",
        case_id="case-drain",
        analysis_run_id="run-drain",
        file_id="file-1",
        file_path="service.log",
        line_number=index,
        line_numbers=[index],
        timestamp=datetime(2026, 6, 7, 8, 0, tzinfo=UTC) + timedelta(seconds=index),
        level="ERROR",
        service=service,
        message=message,
        normalized_message=message,
        redacted_message=message,
        ingestion_order=index,
    )


@pytest.mark.skipif(not Drain3Adapter().available, reason="drain3 is not installed")
def test_drain3_groups_variable_values_and_masks_high_cardinality_fields() -> None:
    logs = [
        _line(1, "cache-service connection pool exhausted active=40 max=40 request_id=req-a"),
        _line(2, "cache-service connection pool exhausted active=39 max=40 request_id=req-b"),
        _line(3, "cache-service connection pool exhausted active=38 max=40 request_id=req-c"),
    ]

    _, templates = Drain3Adapter().cluster(
        case_id="case-drain", analysis_run_id="run-drain", logs=logs
    )

    assert len(templates) == 1
    assert templates[0].sample_values["parser"] == "drain3"
    assert templates[0].occurrence_count == 3
    assert "active=<*>" in templates[0].template_text
    assert "request_id=<*>" in templates[0].template_text
    assert {line.template_id for line in logs} == {templates[0].template_id}


@pytest.mark.skipif(not Drain3Adapter().available, reason="drain3 is not installed")
def test_drain3_templates_feed_sampling_and_label_broadcasting() -> None:
    logs = [
        _line(1, "worker timeout calling scheduler-service job_id=job-1 after 5000ms"),
        _line(2, "worker timeout calling scheduler-service job_id=job-2 after 6000ms"),
    ]

    _, templates = Drain3Adapter(config=DrainConfig(sim_th=0.35)).cluster(
        case_id="case-drain", analysis_run_id="run-drain", logs=logs
    )
    samples = select_samples(logs, templates)
    annotations = [
        TemplateAnnotation(
            annotation_id="ann-1",
            template_id=templates[0].template_id,
            analysis_run_id="run-drain",
            golden_signal="availability",
            fault_categories=["timeout"],
            entities={"service": ["scheduler-service"]},
            severity_score=0.8,
            confidence=0.9,
            rationale="template-level timeout evidence",
        )
    ]

    enriched = broadcast_annotations(logs, annotations)

    assert len(samples) == 1
    assert all(line.golden_signal == "availability" for line in enriched)
    assert all(line.fault_categories == ["timeout"] for line in enriched)


def test_stable_drain_adapter_remains_explicit_fallback() -> None:
    adapter = build_drain_adapter(config={"engine": "stable"})

    assert isinstance(adapter, StableDrainAdapter)
    assert not isinstance(adapter, Drain3Adapter)
    assert "/tenant/acme/private" not in adapter.to_template(
        "GET /tenant/acme/private failed status=500 trace-abc"
    )
