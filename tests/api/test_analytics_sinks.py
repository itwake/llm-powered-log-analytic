from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from logan_workers.activities.inference import MockCopilotAnnotationGateway
from logan_workers.models import (
    AnalysisResult,
    CausalGraph,
    CausalSummary,
    LogEntry,
    NormalizedLogLine,
    WindowAggregate,
)

from app.config import Settings
from app.services.analytics_sinks import (
    AnalyticsSinkError,
    AnalyticsSinkPublisher,
    build_clickhouse_enriched_log_rows,
    build_clickhouse_window_rows,
    build_opensearch_log_documents,
    opensearch_index_name,
)
from app.sqlalchemy_store import SQLAlchemyStore


FIXTURE_DIR = Path("tests/fixtures/logs/checkout_incident")
FORBIDDEN_PAYLOAD_KEYS = {
    "raw_message",
    "raw_text",
    "model_inputs",
    "case_context",
    "representative_lines",
    "template_context",
}


def _analysis_result() -> AnalysisResult:
    timestamp = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    logs = [
        NormalizedLogLine(
            log_id="log-1",
            raw_log_id="raw-1",
            case_id="Case A",
            analysis_run_id="Run A",
            file_id="file-1",
            file_path="/var/log/auth.log",
            line_number=7,
            line_numbers=[7],
            timestamp=timestamp,
            level="ERROR",
            service="auth-service",
            message="login failed Authorization=Bearer secret-token password=hunter2",
            normalized_message="login failed authorization=bearer <secret> password=<secret>",
            redacted_message="login failed Authorization=Bearer <SECRET> password=<SECRET>",
            parser_confidence=0.95,
            ingestion_order=1,
            template_id="template-1",
            template_text="login failed authorization=bearer <*> password=<*>",
            golden_signal="error",
            fault_categories=["authentication"],
            entities={"service": ["auth-service"]},
            severity_score=0.84,
            confidence=0.9,
        ),
        NormalizedLogLine(
            log_id="log-2",
            raw_log_id="raw-2",
            case_id="Case A",
            analysis_run_id="Run A",
            file_id="file-1",
            file_path="/var/log/auth.log",
            line_number=8,
            line_numbers=[8, 9],
            timestamp=timestamp + timedelta(seconds=5),
            level="WARN",
            service="auth-service",
            message="retrying auth lookup request_id=req-123",
            normalized_message="retrying auth lookup request_id=req-123",
            redacted_message="retrying auth lookup request_id=req-123",
            parser_confidence=0.9,
            ingestion_order=2,
            template_id="template-2",
            template_text="retrying auth lookup request_id=<*>",
            golden_signal="traffic",
            fault_categories=["retry"],
            entities={"request_id": ["req-123"]},
            severity_score=0.42,
            confidence=0.71,
        ),
    ]
    return AnalysisResult(
        case_id="Case A",
        analysis_run_id="Run A",
        files=[],
        raw_entries=[
            LogEntry(
                log_id="raw-1",
                file_id="file-1",
                file_path="/var/log/auth.log",
                line_number=7,
                line_numbers=[7],
                raw_message="login failed Authorization=Bearer secret-token password=hunter2",
                raw_line_ids=["physical-1"],
                sha256="sha-1",
                ingestion_order=1,
            )
        ],
        normalized_logs=logs,
        templates=[],
        samples=[],
        annotations=[],
        temporal=[
            WindowAggregate(
                window_start=timestamp,
                window_end=timestamp + timedelta(minutes=1),
                window_size_seconds=60,
                template_id="template-1",
                service="auth-service",
                golden_signal="error",
                fault_category="authentication",
                count=1,
            )
        ],
        causal_graph=CausalGraph(nodes=[], edges=[], root_cause_candidates=[]),
        causal_summary=CausalSummary(
            summary_markdown="summary",
            customer_update_markdown="update",
            next_actions=[],
            evidence_refs=[logs[0].evidence_ref()],
            confidence=0.7,
        ),
        exports={},
        model_inputs=[
            {
                "case_context": {"token": "secret-token"},
                "template_context": {"template": "raw"},
                "representative_lines": [{"message": "hunter2"}],
            }
        ],
    )


def _assert_forbidden_keys_absent(value: Any) -> None:
    if isinstance(value, dict):
        assert FORBIDDEN_PAYLOAD_KEYS.isdisjoint(value)
        for nested in value.values():
            _assert_forbidden_keys_absent(nested)
    elif isinstance(value, list):
        for item in value:
            _assert_forbidden_keys_absent(item)


def test_payload_builders_emit_redacted_analytics_without_sensitive_fields() -> None:
    result = _analysis_result()

    clickhouse_logs = build_clickhouse_enriched_log_rows(result)
    clickhouse_windows = build_clickhouse_window_rows(result)
    opensearch_docs = build_opensearch_log_documents(result)

    assert len(clickhouse_logs) == len(result.normalized_logs)
    assert len(clickhouse_windows) == len(result.temporal)
    assert len(opensearch_docs) == len(result.normalized_logs)

    payload = [*clickhouse_logs, *clickhouse_windows, *opensearch_docs]
    _assert_forbidden_keys_absent(payload)
    serialized = json.dumps(payload, sort_keys=True)
    assert "<SECRET>" in serialized
    assert "secret-token" not in serialized
    assert "hunter2" not in serialized


def test_opensearch_index_name_is_lowercase_and_safe() -> None:
    assert opensearch_index_name("Case A/01", "Run:02") == "logan-logs-case-a-01-run-02"


def test_clickhouse_publisher_sends_two_json_each_row_posts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    publisher = AnalyticsSinkPublisher(
        clickhouse_url="http://clickhouse:8123",
        clickhouse_database="logan",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    publish_result = publisher.publish(_analysis_result())

    assert publish_result.clickhouse_enriched_log_rows == 2
    assert publish_result.clickhouse_window_rows == 1
    assert publish_result.opensearch_documents == 0
    assert len(requests) == 2
    assert requests[0].url.params["query"] == (
        "INSERT INTO logan.enriched_log_lines FORMAT JSONEachRow"
    )
    assert requests[1].url.params["query"] == (
        "INSERT INTO logan.window_aggregates FORMAT JSONEachRow"
    )
    first_body = requests[0].content.decode()
    assert first_body.endswith("\n")
    assert "redacted_message" in first_body
    assert "secret-token" not in first_body


def test_opensearch_publisher_sends_bulk_ndjson() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    result = _analysis_result()
    publisher = AnalyticsSinkPublisher(
        opensearch_url="http://opensearch:9200",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    publish_result = publisher.publish(result)

    assert publish_result.clickhouse_enriched_log_rows == 0
    assert publish_result.clickhouse_window_rows == 0
    assert publish_result.opensearch_documents == 2
    assert len(requests) == 1
    assert requests[0].url.path == "/_bulk"
    assert requests[0].headers["content-type"] == "application/x-ndjson"
    bulk_lines = [json.loads(line) for line in requests[0].content.decode().splitlines()]
    assert len(bulk_lines) == 4
    assert bulk_lines[0]["index"]["_index"] == opensearch_index_name(
        result.case_id, result.analysis_run_id
    )
    assert bulk_lines[1]["log_id"] == "log-1"
    assert bulk_lines[1]["redacted_message"]
    assert "secret-token" not in requests[0].content.decode()


def test_publisher_raises_typed_error_on_non_2xx_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    publisher = AnalyticsSinkPublisher(
        clickhouse_url="http://clickhouse:8123",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AnalyticsSinkError, match="HTTP 503"):
        publisher.publish(_analysis_result())


class FailingPublisher:
    def publish(self, _result: AnalysisResult) -> dict[str, int]:
        raise AnalyticsSinkError("sink unavailable")


@pytest.mark.asyncio
async def test_sqlalchemy_warn_mode_audits_sink_error_without_failing_run(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        analytics_sinks_enabled=True,
        clickhouse_url="http://clickhouse:8123",
        analytics_sink_failure_mode="warn",
    )
    store = SQLAlchemyStore(
        app_settings=app_settings,
        database_url=database_url,
        analytics_sink_publisher=FailingPublisher(),
    )
    user = store.register_user(
        email="sink.warn@example.com",
        username="sink-warn",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Sink warning analysis",
            "issue_description": "External sink should not fail default runs.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "timezone": "UTC",
        },
    )

    run = await store.start_analysis(
        case_id=case.id,
        user_id=user.id,
        input_paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
        config={"default_window_size_seconds": 60},
        gateway=MockCopilotAnnotationGateway(),
    )

    assert run.status == "completed"
    audit_actions = [record.action for record in store.list_audit_logs(case_id=case.id)]
    assert "analytics_sink.publish_failed" in audit_actions
    assert "analysis.complete" in audit_actions
    failures = store.list_audit_logs(case_id=case.id, action="analytics_sink.publish_failed")
    assert failures[0].metadata["failure_mode"] == "warn"
    assert "sink unavailable" in failures[0].metadata["error"]
