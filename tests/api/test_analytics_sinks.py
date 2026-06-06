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
from app.models import tables
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


def _seed_sink_run(store: SQLAlchemyStore, result: AnalysisResult) -> str:
    user_id = "sink-user"
    with store._session() as session:
        session.add(
            tables.User(
                id=user_id,
                email="sink-user@example.com",
                username="sink-user",
                password_hash="hash",
                role="engineer",
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            tables.Case(
                id=result.case_id,
                case_key="LOGAN-SINK-0001",
                title="Sink publish",
                created_by=user_id,
                status="processing",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            tables.AnalysisRun(
                id=result.analysis_run_id,
                case_id=result.case_id,
                run_number=1,
                status="processing",
                config_json={},
                model_provider="test",
                model_name="mock",
                model_reasoning_effort="low",
                prompt_version="test",
                drain_config_json={},
                causal_config_json={},
                progress_json={},
                started_at=datetime.now(UTC),
                created_by=user_id,
                created_at=datetime.now(UTC),
            )
        )
    return user_id


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


def test_clickhouse_publisher_manages_database_and_tables_before_inserts() -> None:
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
    assert len(requests) == 5
    queries = [request.url.params["query"] for request in requests]
    assert queries[0] == "CREATE DATABASE IF NOT EXISTS logan"
    assert queries[1].startswith(
        "CREATE TABLE IF NOT EXISTS logan.enriched_log_lines"
    )
    assert "MergeTree" in queries[1]
    assert "redacted_message String" in queries[1]
    assert queries[2].startswith(
        "CREATE TABLE IF NOT EXISTS logan.window_aggregates"
    )
    assert "MergeTree" in queries[2]
    assert queries[3] == (
        "INSERT INTO logan.enriched_log_lines FORMAT JSONEachRow"
    )
    assert queries[4] == (
        "INSERT INTO logan.window_aggregates FORMAT JSONEachRow"
    )
    lifecycle_payload = "\n".join(
        f"{request.url.params['query']} {request.content.decode()}"
        for request in requests[:3]
    )
    assert "secret-token" not in lifecycle_payload
    assert "hunter2" not in lifecycle_payload
    first_body = requests[3].content.decode()
    assert first_body.endswith("\n")
    assert "redacted_message" in first_body
    assert "secret-token" not in first_body


def test_opensearch_publisher_manages_index_before_bulk_ndjson() -> None:
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
    index_name = opensearch_index_name(result.case_id, result.analysis_run_id)
    assert len(requests) == 2
    assert requests[0].method == "PUT"
    assert requests[0].url.path == f"/{index_name}"
    mapping_body = json.loads(requests[0].content.decode())
    assert mapping_body["mappings"]["properties"]["case_id"]["type"] == "keyword"
    assert mapping_body["mappings"]["properties"]["timestamp"]["type"] == "date"
    assert mapping_body["mappings"]["properties"]["search_text"]["type"] == "text"
    assert "secret-token" not in requests[0].content.decode()
    assert requests[1].method == "POST"
    assert requests[1].url.path == "/_bulk"
    assert requests[1].headers["content-type"] == "application/x-ndjson"
    bulk_lines = [json.loads(line) for line in requests[1].content.decode().splitlines()]
    assert len(bulk_lines) == 4
    assert bulk_lines[0]["index"]["_index"] == index_name
    assert bulk_lines[1]["log_id"] == "log-1"
    assert bulk_lines[1]["redacted_message"]
    assert "secret-token" not in requests[1].content.decode()


def test_opensearch_index_already_exists_is_success() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(
                400,
                json={"error": {"type": "resource_already_exists_exception"}},
            )
        return httpx.Response(200)

    publisher = AnalyticsSinkPublisher(
        opensearch_url="http://opensearch:9200",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    publish_result = publisher.publish(_analysis_result())

    assert publish_result.opensearch_documents == 2
    assert [request.method for request in requests] == ["PUT", "POST"]


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


def test_sqlalchemy_sink_writes_skip_succeeded_targets(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    result = _analysis_result()
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        analytics_sinks_enabled=True,
        clickhouse_url="http://clickhouse:8123",
        opensearch_url="http://opensearch:9200",
        analytics_sink_failure_mode="warn",
    )
    publisher = AnalyticsSinkPublisher(
        clickhouse_url=app_settings.clickhouse_url,
        clickhouse_database=app_settings.clickhouse_database,
        opensearch_url=app_settings.opensearch_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store = SQLAlchemyStore(
        app_settings=app_settings,
        database_url=database_url,
        analytics_sink_publisher=publisher,
    )
    user_id = _seed_sink_run(store, result)

    store._publish_analytics_sinks(
        run_id=result.analysis_run_id,
        result=result,
        user_id=user_id,
    )

    assert [request.method for request in requests] == [
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "PUT",
        "POST",
    ]
    writes = store.list_analytics_sink_writes(
        case_id=result.case_id,
        analysis_run_id=result.analysis_run_id,
    )
    assert len(writes) == 3
    assert {write.destination for write in writes} == {
        "logan.enriched_log_lines",
        "logan.window_aggregates",
        f"{opensearch_index_name(result.case_id, result.analysis_run_id)}/_bulk",
    }
    assert {write.status for write in writes} == {"succeeded"}
    assert {write.attempt_count for write in writes} == {1}
    persisted = json.dumps([write.__dict__ for write in writes], default=str)
    assert "secret-token" not in persisted
    assert "hunter2" not in persisted
    first_request_count = len(requests)

    store._publish_analytics_sinks(
        run_id=result.analysis_run_id,
        result=result,
        user_id=user_id,
    )

    assert len(requests) == first_request_count
    writes_after_skip = store.list_analytics_sink_writes(
        case_id=result.case_id,
        analysis_run_id=result.analysis_run_id,
    )
    assert {write.attempt_count for write in writes_after_skip} == {1}
    publish_audits = store.list_audit_logs(
        case_id=result.case_id, action="analytics_sink.publish"
    )
    assert publish_audits[-1].metadata["skipped_writes"] == 3


def test_sqlalchemy_failed_sink_write_retries_next_publish(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    enriched_insert_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal enriched_insert_attempts
        requests.append(request)
        query = request.url.params.get("query", "")
        if query == "INSERT INTO logan.enriched_log_lines FORMAT JSONEachRow":
            enriched_insert_attempts += 1
            if enriched_insert_attempts == 1:
                return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200)

    result = _analysis_result()
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        analytics_sinks_enabled=True,
        clickhouse_url="http://clickhouse:8123",
        analytics_sink_failure_mode="warn",
    )
    publisher = AnalyticsSinkPublisher(
        clickhouse_url=app_settings.clickhouse_url,
        clickhouse_database=app_settings.clickhouse_database,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store = SQLAlchemyStore(
        app_settings=app_settings,
        database_url=database_url,
        analytics_sink_publisher=publisher,
    )
    user_id = _seed_sink_run(store, result)

    store._publish_analytics_sinks(
        run_id=result.analysis_run_id,
        result=result,
        user_id=user_id,
    )

    writes = {
        write.destination: write
        for write in store.list_analytics_sink_writes(
            case_id=result.case_id,
            analysis_run_id=result.analysis_run_id,
        )
    }
    assert writes["logan.enriched_log_lines"].status == "failed"
    assert writes["logan.enriched_log_lines"].attempt_count == 1
    assert writes["logan.window_aggregates"].status == "succeeded"
    assert writes["logan.window_aggregates"].attempt_count == 1
    assert store.list_audit_logs(
        case_id=result.case_id, action="analytics_sink.publish_failed"
    )
    first_request_count = len(requests)

    store._publish_analytics_sinks(
        run_id=result.analysis_run_id,
        result=result,
        user_id=user_id,
    )

    assert enriched_insert_attempts == 2
    assert len(requests) == first_request_count + 4
    writes_after_retry = {
        write.destination: write
        for write in store.list_analytics_sink_writes(
            case_id=result.case_id,
            analysis_run_id=result.analysis_run_id,
        )
    }
    assert writes_after_retry["logan.enriched_log_lines"].status == "succeeded"
    assert writes_after_retry["logan.enriched_log_lines"].attempt_count == 2
    assert writes_after_retry["logan.window_aggregates"].attempt_count == 1


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
    writes = store.list_analytics_sink_writes(case_id=case.id, analysis_run_id=run.id)
    assert len(writes) == 1
    assert writes[0].status == "failed"
    assert writes[0].attempt_count == 1
    assert "sink unavailable" in (writes[0].last_error or "")


@pytest.mark.asyncio
async def test_sqlalchemy_fail_mode_preserves_sink_write_and_fails_run(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'logan.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        analytics_sinks_enabled=True,
        clickhouse_url="http://clickhouse:8123",
        analytics_sink_failure_mode="fail",
    )
    store = SQLAlchemyStore(
        app_settings=app_settings,
        database_url=database_url,
        analytics_sink_publisher=FailingPublisher(),
    )
    user = store.register_user(
        email="sink.fail@example.com",
        username="sink-fail",
        full_name=None,
        password="password123",
    )
    case = store.create_case(
        user_id=user.id,
        data={
            "title": "Sink failure analysis",
            "issue_description": "External sink should fail strict runs.",
            "product": "commerce-platform",
            "service": "checkout",
            "environment": "test",
            "timezone": "UTC",
        },
    )

    with pytest.raises(AnalyticsSinkError, match="sink unavailable"):
        await store.start_analysis(
            case_id=case.id,
            user_id=user.id,
            input_paths=[str(path) for path in sorted(FIXTURE_DIR.glob("*.log"))],
            config={"default_window_size_seconds": 60},
            gateway=MockCopilotAnnotationGateway(),
        )

    run = store.list_analysis_runs(case.id)[0]
    assert run.status == "failed"
    writes = store.list_analytics_sink_writes(case_id=case.id, analysis_run_id=run.id)
    assert len(writes) == 1
    assert writes[0].status == "failed"
    assert writes[0].attempt_count == 1
    audit_actions = [record.action for record in store.list_audit_logs(case_id=case.id)]
    assert "analytics_sink.publish_failed" in audit_actions
    assert "analysis.fail" in audit_actions
    assert "analysis.complete" not in audit_actions
