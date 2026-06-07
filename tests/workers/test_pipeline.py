from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.observability import metrics_text
from logan_workers.activities.ingestion import ingest_paths
from logan_workers.activities.inference import MockCopilotAnnotationGateway
from logan_workers.activities.preprocessing import merge_entries, preprocess_entries
from logan_workers.algorithms.redactors import redact_text
from logan_workers.models import OFFENDING_SIGNALS
from logan_workers.pipeline import AnalyzeCasePipeline


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")


def _write_scheduler_fixture(tmp_path: Path) -> list[str]:
    log_file = tmp_path / "scheduler_incident.log"
    log_file.write_text(
        "\n".join(
            [
                (
                    "2026-06-06T10:00:00Z WARN cache-service connection pool exhausted "
                    "active=40 max=40"
                ),
                (
                    "2026-06-06T10:00:30Z ERROR scheduler-service timeout calling "
                    "cache-service after 5000ms job_id=job-1"
                ),
                (
                    "2026-06-06T10:01:00Z ERROR kafka-consumer failed processing schedule "
                    "event due scheduler-service timeout topic=schedules"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return [str(log_file)]


class FailingAnnotationGateway(MockCopilotAnnotationGateway):
    async def responses(self, **kwargs):
        raise RuntimeError("annotation failed token=gho_pipeline_secret_token password=hunter2")


class FailingSummaryGateway(MockCopilotAnnotationGateway):
    async def responses(self, **kwargs):
        metadata = kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else {}
        if metadata.get("purpose") == "causal_summary":
            self.calls.append(kwargs)
            raise RuntimeError("summary failed token=gho_summary_secret password=hunter2")
        return await super().responses(**kwargs)


class InvalidSummaryGateway(MockCopilotAnnotationGateway):
    async def responses(self, **kwargs):
        metadata = kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else {}
        if metadata.get("purpose") == "causal_summary":
            self.calls.append(kwargs)
            return {"output_json": {"summary": "not the required schema"}}
        return await super().responses(**kwargs)


def _summary_gateway_payload(gateway: MockCopilotAnnotationGateway) -> tuple[dict, str]:
    summary_calls = [
        call
        for call in gateway.calls
        if isinstance(call.get("metadata"), dict)
        and call["metadata"].get("purpose") == "causal_summary"
    ]
    assert len(summary_calls) == 1
    call = summary_calls[0]
    text = call["input"][0]["content"][0]["text"]
    return call, text


@pytest.mark.asyncio
async def test_pipeline_checkout_incident_end_to_end() -> None:
    gateway = MockCopilotAnnotationGateway()
    result = await AnalyzeCasePipeline().run(
        case_id="case-1",
        analysis_run_id="run-1",
        paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
        case_context={
            "title": "Checkout API intermittent 500 errors",
            "issue_description": "Customers report intermittent 500 during checkout.",
            "product": "commerce-platform",
            "environment": "production",
        },
        gateway=gateway,
    )

    raw_lines = sum(len(file.lines) for file in result.files)
    assert raw_lines == 9
    assert len(result.templates) < raw_lines
    assert len(result.samples) >= len(result.templates)
    assert {annotation.golden_signal for annotation in result.annotations} >= {
        "saturation",
        "availability",
        "error",
    }

    payment_timeout_template_ids = {
        line.template_id
        for line in result.normalized_logs
        if "timeout calling auth-service" in line.message
    }
    assert payment_timeout_template_ids
    for line in result.normalized_logs:
        if line.template_id in payment_timeout_template_ids:
            assert line.golden_signal == "availability"
            assert "timeout" in line.fault_categories

    offending_templates = {
        annotation.template_id
        for annotation in result.annotations
        if annotation.golden_signal in OFFENDING_SIGNALS
    }
    assert offending_templates

    assert any(point.golden_signal == "error" and point.count > 0 for point in result.temporal)
    assert any(
        point.golden_signal == "availability" and point.count > 0 for point in result.temporal
    )

    edges = result.causal_graph.edges
    assert edges
    assert all(edge.edge_type == "candidate_cause" for edge in edges)
    assert all(edge.needs_validation for edge in edges)
    assert all(edge.evidence.get("source_template_id") for edge in edges)
    method_evidence = [edge.evidence.get("methods", {}) for edge in edges]
    assert all("extension_seam" not in methods.get("pgem", {}) for methods in method_evidence)
    assert all(
        "extension_seam" not in methods.get("granger_linear", {})
        for methods in method_evidence
    )
    assert all("supported" in methods.get("pgem", {}) for methods in method_evidence)
    assert all("supported" in methods.get("granger_linear", {}) for methods in method_evidence)
    assert any(
        methods["pgem"]["supported"] or methods["granger_linear"]["supported"]
        for methods in method_evidence
    )
    assert all(
        "pgem" in edge.method
        for edge in edges
        if edge.evidence["methods"]["pgem"]["supported"]
    )
    assert all(
        "granger_linear" in edge.method
        for edge in edges
        if edge.evidence["methods"]["granger_linear"]["supported"]
    )
    assert any(
        "auth-service" in edge.evidence.get("source_template_id", "")
        or "service_entity" in edge.method
        for edge in edges
    )

    markdown = result.causal_summary.summary_markdown.lower()
    assert "candidate" in markdown
    assert "needs validation" in markdown
    assert result.causal_summary.evidence_refs
    assert result.causal_summary.evidence_claims
    assert result.causal_summary.uncertainties
    assert result.causal_summary.details["source"] == "llm"

    call, summary_packet = _summary_gateway_payload(gateway)
    assert call["metadata"]["purpose"] == "causal_summary"
    assert call["metadata"]["prompt_version"] == "causal_summary_v1"
    assert "auth-service" in summary_packet
    assert "payment-service" in summary_packet
    assert "gateway" in summary_packet
    assert "raw_message" not in summary_packet
    assert "raw_text" not in summary_packet
    assert "model_inputs" not in summary_packet
    assert "prompt" not in summary_packet
    assert "password" not in summary_packet
    assert "api_key" not in summary_packet
    assert "authorization" not in summary_packet

    assert result.exports["markdown"].content.startswith("# Incident Diagnosis Summary")
    assert result.exports["html"].content.startswith("<!doctype html>")
    parsed_export = json.loads(result.exports["json"].content)
    assert parsed_export["causal_graph"]["edges"]


@pytest.mark.asyncio
async def test_mock_causal_summary_uses_packet_terms_for_non_checkout_fixture(
    tmp_path: Path,
) -> None:
    gateway = MockCopilotAnnotationGateway()
    result = await AnalyzeCasePipeline().run(
        case_id="case-scheduler",
        analysis_run_id="run-scheduler",
        paths=_write_scheduler_fixture(tmp_path),
        gateway=gateway,
    )

    markdown = result.causal_summary.summary_markdown.lower()
    assert result.causal_summary.details["source"] == "llm"
    assert "candidate source signal" in markdown
    assert "downstream symptom" in markdown
    assert "cache-service" in markdown
    assert "scheduler-service" in markdown
    assert result.causal_summary.evidence_claims[0]["evidence_refs"]
    for leaked_term in ("checkout", "auth-service", "payment-service", "/checkout"):
        assert leaked_term not in markdown

    _, summary_packet = _summary_gateway_payload(gateway)
    packet = json.loads(summary_packet)
    packet_log_ids = {line["log_id"] for line in packet["evidence_lines"]}
    claim_refs = set(result.causal_summary.evidence_claims[0]["evidence_refs"])
    assert claim_refs <= packet_log_ids
    assert packet["root_cause_candidates"]


@pytest.mark.asyncio
@pytest.mark.parametrize("gateway_cls", [FailingSummaryGateway, InvalidSummaryGateway])
async def test_causal_summary_falls_back_to_evidence_when_gateway_unavailable_or_invalid(
    gateway_cls,
) -> None:
    gateway = gateway_cls()
    result = await AnalyzeCasePipeline().run(
        case_id="case-summary-fallback",
        analysis_run_id="run-summary-fallback",
        paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
        gateway=gateway,
    )

    markdown = result.causal_summary.summary_markdown.lower()
    assert result.causal_summary.details["source"] == "fallback"
    assert (
        "gateway_unavailable_or_invalid_model_output"
        in result.causal_summary.details["fallback_reason"]
    )
    assert "candidate" in markdown
    assert "needs validation" in markdown
    assert "auth-service" in markdown
    assert "payment-service" in markdown
    assert "gateway" in markdown
    assert result.causal_summary.evidence_refs
    assert result.causal_summary.evidence_claims
    assert result.causal_summary.uncertainties
    _summary_gateway_payload(gateway)


@pytest.mark.asyncio
async def test_causal_summary_fallback_is_domain_neutral_for_scheduler_incident(
    tmp_path: Path,
) -> None:
    gateway = FailingSummaryGateway()
    result = await AnalyzeCasePipeline().run(
        case_id="case-scheduler-fallback",
        analysis_run_id="run-scheduler-fallback",
        paths=_write_scheduler_fixture(tmp_path),
        gateway=gateway,
    )

    assert result.causal_summary.details["source"] == "fallback"
    rendered_actions = json.dumps(result.causal_summary.next_actions).lower()
    rendered_claims = json.dumps(result.causal_summary.evidence_claims).lower()
    combined = " ".join(
        [
            result.causal_summary.summary_markdown.lower(),
            result.causal_summary.customer_update_markdown.lower(),
            rendered_actions,
            rendered_claims,
        ]
    )
    assert "candidate source signal" in combined
    assert "downstream symptom" in combined
    assert "affected service" in combined
    assert "dependency/resource signal" in combined
    assert "cache-service" in combined
    assert "scheduler-service" in combined
    for leaked_term in ("checkout", "auth-service", "payment-service", "/checkout"):
        assert leaked_term not in combined
    _summary_gateway_payload(gateway)


def test_multiline_merge_keeps_original_line_refs(tmp_path: Path) -> None:
    log_file = tmp_path / "stack.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-06-06T10:12:00Z ERROR api-service Traceback (most recent call last):",
                "  File \"checkout.py\", line 10, in run",
                "    raise RuntimeError('boom')",
                "RuntimeError: boom",
                "2026-06-06T10:12:01Z INFO api-service recovered",
            ]
        ),
        encoding="utf-8",
    )
    files = ingest_paths([log_file])
    entries = merge_entries(files)
    normalized = preprocess_entries(case_id="case", analysis_run_id="run", entries=entries)
    assert len(entries) == 2
    assert entries[0].line_numbers == [1, 2, 3, 4]
    assert normalized[0].parsed_fields["stack_trace_lines"] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_pipeline_emits_step_progress_events() -> None:
    events: list[dict[str, object]] = []

    async def collect(event: dict[str, object]) -> None:
        events.append(dict(event))

    result = await AnalyzeCasePipeline().run(
        case_id="case-events",
        analysis_run_id="run-events",
        paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
        progress_callback=collect,
    )

    expected_steps = [
        "ingest_paths",
        "merge_entries",
        "preprocess_redact",
        "drain_templating",
        "representative_sampling",
        "copilot_annotation",
        "broadcast_annotations",
        "temporal_aggregation",
        "causal_graph",
        "causal_summary",
        "export_artifacts",
    ]
    assert [
        event["step_name"] for event in events if event["event_type"] == "completed"
    ] == expected_steps
    assert all(event["analysis_run_id"] == "run-events" for event in events)
    assert result.progress["current_step"] == "completed"
    assert result.progress["steps"]["copilot_annotation"]["metadata"]["annotations"] > 0
    body = metrics_text()
    assert 'logan_pipeline_runs_total{status="started"}' in body
    assert 'logan_pipeline_runs_total{status="completed"}' in body
    assert 'logan_pipeline_steps_total{status="started",step_name="ingest_paths"}' in body
    assert 'logan_pipeline_steps_total{status="completed",step_name="export_artifacts"}' in body
    assert (
        'logan_pipeline_step_duration_seconds_count{status="completed",'
        'step_name="export_artifacts"}'
    ) in body


@pytest.mark.asyncio
async def test_pipeline_metrics_record_failure_without_sensitive_error_labels() -> None:
    with pytest.raises(RuntimeError):
        await AnalyzeCasePipeline().run(
            case_id="case-metrics-fail",
            analysis_run_id="run-metrics-fail",
            paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            gateway=FailingAnnotationGateway(),
        )

    body = metrics_text()
    assert 'logan_pipeline_runs_total{status="failed"}' in body
    assert 'logan_pipeline_steps_total{status="failed",step_name="copilot_annotation"}' in body
    assert (
        'logan_pipeline_step_duration_seconds_count{status="failed",'
        'step_name="copilot_annotation"}'
    ) in body
    assert "gho_pipeline_secret_token" not in body
    assert "hunter2" not in body


@pytest.mark.asyncio
async def test_redaction_happens_before_model_input(tmp_path: Path) -> None:
    log_file = tmp_path / "sensitive.log"
    log_file.write_text(
        "2026-06-06T10:12:00Z ERROR auth-service login failed email=alice@example.com "
        "ip=192.168.1.10 Authorization=Bearer abc.def.ghi password=hunter2 "
        "tenant_id=customer-123\n",
        encoding="utf-8",
    )
    gateway = MockCopilotAnnotationGateway()
    result = await AnalyzeCasePipeline().run(
        case_id="case-redaction",
        analysis_run_id="run-redaction",
        paths=[str(log_file)],
        gateway=gateway,
    )
    model_payload = json.dumps(result.model_inputs)
    assert "alice@example.com" not in model_payload
    assert "192.168.1.10" not in model_payload
    assert "hunter2" not in model_payload
    assert "customer-123" not in model_payload
    assert "<EMAIL>" in model_payload
    assert "<IP>" in model_payload
    assert "<SECRET>" in model_payload
    assert "<TENANT_ID>" in model_payload
    _, summary_packet = _summary_gateway_payload(gateway)
    assert "alice@example.com" not in summary_packet
    assert "192.168.1.10" not in summary_packet
    assert "hunter2" not in summary_packet
    assert "customer-123" not in summary_packet
    assert "raw_message" not in summary_packet
    assert "raw_text" not in summary_packet
    assert "model_inputs" not in summary_packet
    assert "password" not in summary_packet
    assert "token" not in summary_packet
    assert "api_key" not in summary_packet
    assert "redacted_message" in summary_packet


def test_redactor_masks_url_query_and_tokens() -> None:
    text = redact_text(
        "GET /callback?token=abc123&api_key=xyz&source_token=query-secret "
        "source_token=assignment-secret bearer Bearer secret.jwt.value "
        "card 4111111111111111"
    )
    assert "abc123" not in text
    assert "xyz" not in text
    assert "query-secret" not in text
    assert "assignment-secret" not in text
    assert "secret.jwt.value" not in text
    assert "4111111111111111" not in text
    assert "<SECRET>" in text
    assert "<TOKEN>" in text
    assert "<CARD>" in text
