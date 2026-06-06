from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.models import tables
from app.services.analytics_queries import AnalyticsQueryClient
from app.services.analytics_sinks import opensearch_index_name
from app.sqlalchemy_store import SQLAlchemyStore


def _new_id() -> str:
    return str(uuid.uuid4())


def _store(tmp_path: Path, **settings_overrides: Any) -> SQLAlchemyStore:
    database_url = f"sqlite:///{tmp_path / f'{uuid.uuid4()}.db'}"
    app_settings = Settings(
        database_url=database_url,
        store_backend="sqlalchemy",
        **settings_overrides,
    )
    return SQLAlchemyStore(app_settings=app_settings, database_url=database_url)


def _seed_case_run(store: SQLAlchemyStore) -> tuple[str, str]:
    user_id = _new_id()
    case_id = _new_id()
    run_id = _new_id()
    now = datetime.now(UTC)
    with store._session() as session:
        session.add(
            tables.User(
                id=user_id,
                email=f"{user_id}@example.com",
                username=f"user-{user_id}",
                password_hash="hash",
                role="engineer",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            tables.Case(
                id=case_id,
                case_key=f"LOGAN-{case_id}",
                title="External query case",
                created_by=user_id,
                status="completed",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            tables.AnalysisRun(
                id=run_id,
                case_id=case_id,
                run_number=1,
                status="completed",
                config_json={},
                model_provider="test",
                model_name="mock",
                model_reasoning_effort="low",
                prompt_version="test",
                drain_config_json={},
                causal_config_json={},
                progress_json={},
                started_at=now,
                completed_at=now,
                created_by=user_id,
                created_at=now,
            )
        )
    return case_id, run_id


def _seed_sink_write(
    store: SQLAlchemyStore,
    *,
    case_id: str,
    run_id: str,
    sink_name: str,
    destination: str,
    status: str = "succeeded",
) -> None:
    now = datetime.now(UTC)
    with store._session() as session:
        session.add(
            tables.AnalyticsSinkWrite(
                id=_new_id(),
                case_id=case_id,
                analysis_run_id=run_id,
                sink_name=sink_name,
                destination=destination,
                idempotency_key=f"{sink_name}:{destination}:{uuid.uuid4()}",
                payload_hash="payload-hash",
                status=status,
                attempt_count=1,
                row_count=1,
                created_at=now,
                updated_at=now,
            )
        )


def _seed_temporal_fanout(store: SQLAlchemyStore, *, case_id: str, run_id: str) -> None:
    start = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    with store._session() as session:
        session.add(
            tables.TimeWindowSignal(
                id=_new_id(),
                case_id=case_id,
                analysis_run_id=run_id,
                window_start=start,
                window_end=start + timedelta(minutes=1),
                window_size_seconds=60,
                service="sql-service",
                golden_signal="error",
                fault_category="authentication",
                count=7,
                created_at=datetime.now(UTC),
            )
        )


def _seed_log_fanout(store: SQLAlchemyStore, *, case_id: str, run_id: str) -> None:
    now = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    file_id = _new_id()
    raw_log_id = _new_id()
    line_id = _new_id()
    template_id = _new_id()
    with store._session() as session:
        session.add(
            tables.RawFile(
                id=file_id,
                case_id=case_id,
                analysis_run_id=run_id,
                original_filename="auth.log",
                object_uri="file:///auth.log",
                size_bytes=128,
                upload_completed=True,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            tables.RawLogLine(
                id=raw_log_id,
                case_id=case_id,
                analysis_run_id=run_id,
                file_id=file_id,
                line_number=12,
                raw_text="raw password=hunter2",
                raw_text_redacted="sql fallback <SECRET>",
                sha256="sha",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            tables.LogTemplate(
                id=template_id,
                case_id=case_id,
                analysis_run_id=run_id,
                template_key="auth-template",
                template_text="sql fallback <*>",
                normalized_template_text="sql fallback <*>",
                representative_log_id=line_id,
                occurrence_count=1,
                first_seen=now,
                last_seen=now,
                services=["sql-service"],
                files=["auth.log"],
                sample_values={},
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            tables.NormalizedLogLine(
                id=line_id,
                raw_log_id=raw_log_id,
                case_id=case_id,
                analysis_run_id=run_id,
                timestamp=now,
                timestamp_quality="parsed",
                level="ERROR",
                service="sql-service",
                message="raw password=hunter2",
                normalized_message="sql fallback <secret>",
                redacted_message="sql fallback <SECRET>",
                parsed_fields={"stack_trace_lines": [12, 13]},
                parser_confidence=0.95,
                template_id=template_id,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            tables.TemplateAnnotation(
                id=_new_id(),
                template_id=template_id,
                analysis_run_id=run_id,
                golden_signal="error",
                fault_categories=["authentication"],
                entities={"request_id": ["req-1"]},
                severity_score=0.8,
                confidence=0.9,
                model_provider="test",
                model_name="mock",
                prompt_version="test",
                raw_model_response={},
                created_at=datetime.now(UTC),
            )
        )


def test_clickhouse_temporal_query_returns_report_and_parameterizes_values() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "window_size_seconds": 60,
                        "name": "auth-service",
                        "window_start": "2026-06-06 10:00:00.000",
                        "aggregate_count": "2",
                    },
                    {
                        "window_size_seconds": 60,
                        "name": "auth-service",
                        "window_start": "2026-06-06 10:00:00.000",
                        "aggregate_count": 1,
                    },
                ]
            },
        )

    client = AnalyticsQueryClient(
        enabled=True,
        clickhouse_url="http://clickhouse:8123",
        clickhouse_database="logan",
        clickhouse_username="logan",
        clickhouse_password="secret-password",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    report = client.query_temporal(case_id="Case A", run_id="Run A", group_by="service")

    assert report == {
        "window_size_seconds": 60,
        "series": [
            {
                "name": "auth-service",
                "points": [
                    {"window_start": "2026-06-06T10:00:00+00:00", "count": 3}
                ],
            }
        ],
    }
    assert len(requests) == 1
    request = requests[0]
    query = request.url.params["query"]
    assert request.method == "POST"
    assert request.content == b""
    assert "FROM logan.window_aggregates" in query
    assert "case_id = {case_id:String}" in query
    assert "analysis_run_id = {run_id:String}" in query
    assert "ifNull(nullIf(service, ''), 'unknown')" in query
    assert "Case A" not in query
    assert "Run A" not in query
    assert request.url.params["param_case_id"] == "Case A"
    assert request.url.params["param_run_id"] == "Run A"
    assert "secret-password" not in str(request.url)


def test_opensearch_logs_query_returns_items_facets_and_safe_source_fields() -> None:
    requests: list[httpx.Request] = []
    case_id = "Case A"
    run_id = "Run A"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_source": {
                                "log_id": "log-1",
                                "timestamp": "2026-06-06T10:00:00Z",
                                "level": "ERROR",
                                "service": "auth-service",
                                "file_path": "auth.log",
                                "line_number": 12,
                                "line_numbers": [12, 13],
                                "redacted_message": "token <SECRET>",
                                "template_id": "template-1",
                                "template_text": "token <*>",
                                "golden_signal": "error",
                                "fault_categories": ["authentication"],
                                "entities": {"request_id": ["req-1"]},
                                "raw_text": "password=hunter2",
                                "raw_message": "secret-token",
                            }
                        }
                    ],
                },
                "aggregations": {
                    "service": {"buckets": [{"key": "auth-service", "doc_count": 1}]},
                    "golden_signal": {"buckets": [{"key": "error", "doc_count": 1}]},
                    "fault_category": {
                        "buckets": [{"key": "authentication", "doc_count": 1}]
                    },
                },
            },
        )

    client = AnalyticsQueryClient(
        enabled=True,
        opensearch_url="http://opensearch:9200",
        opensearch_username="logan",
        opensearch_password="secret-password",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    report = client.query_logs(
        case_id=case_id,
        run_id=run_id,
        window_start=datetime(2026, 6, 6, 9, 59, tzinfo=UTC),
        window_end=datetime(2026, 6, 6, 10, 1, tzinfo=UTC),
        q="token",
        service="auth-service",
        limit=25,
        offset=-10,
    )

    assert report["total"] == 1
    assert report["items"] == [
        {
            "log_id": "log-1",
            "timestamp": "2026-06-06T10:00:00+00:00",
            "level": "ERROR",
            "service": "auth-service",
            "file_path": "auth.log",
            "line_number": 12,
            "line_numbers": [12, 13],
            "message": "token <SECRET>",
            "template_id": "template-1",
            "template_text": "token <*>",
            "golden_signal": "error",
            "fault_categories": ["authentication"],
            "entities": {"request_id": ["req-1"]},
        }
    ]
    assert report["facets"]["service"] == [{"value": "auth-service", "count": 1}]
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content.decode())
    assert request.method == "POST"
    assert request.url.path == f"/{opensearch_index_name(case_id, run_id)}/_search"
    assert body["from"] == 0
    assert body["size"] == 25
    assert body["_source"] == [
        "log_id",
        "timestamp",
        "level",
        "service",
        "file_path",
        "line_number",
        "line_numbers",
        "redacted_message",
        "template_id",
        "template_text",
        "golden_signal",
        "fault_categories",
        "entities",
    ]
    assert "raw_text" not in body["_source"]
    assert "raw_message" not in body["_source"]
    assert "search_text" in body["query"]["bool"]["must"][0]["simple_query_string"]["fields"]
    assert {"term": {"service": "auth-service"}} in body["query"]["bool"]["filter"]
    serialized_report = json.dumps(report, sort_keys=True)
    assert "hunter2" not in serialized_report
    assert "secret-token" not in serialized_report
    assert "raw_text" not in serialized_report


class RecordingQueryClient:
    def __init__(self) -> None:
        self.temporal_calls: list[dict[str, object]] = []
        self.log_calls: list[dict[str, object]] = []

    def query_temporal(self, **kwargs: object) -> dict[str, object]:
        self.temporal_calls.append(kwargs)
        return {
            "window_size_seconds": 60,
            "series": [{"name": "external", "points": [{"window_start": "w", "count": 1}]}],
        }

    def query_logs(self, **kwargs: object) -> dict[str, object]:
        self.log_calls.append(kwargs)
        return {
            "items": [{"log_id": "external-log", "message": "external <SECRET>"}],
            "total": 1,
            "facets": {"service": [], "golden_signal": [], "fault_category": []},
        }


def test_sqlalchemy_external_queries_require_opt_in_urls_and_succeeded_writes(
    tmp_path: Path,
) -> None:
    query_client = RecordingQueryClient()
    store = _store(
        tmp_path,
        external_analytics_queries_enabled=True,
        clickhouse_url="http://clickhouse:8123",
        opensearch_url="http://opensearch:9200",
    )
    store.analytics_query_client = query_client
    case_id, run_id = _seed_case_run(store)
    _seed_sink_write(
        store,
        case_id=case_id,
        run_id=run_id,
        sink_name="clickhouse",
        destination="logan.window_aggregates",
    )
    _seed_sink_write(
        store,
        case_id=case_id,
        run_id=run_id,
        sink_name="opensearch",
        destination=f"{opensearch_index_name(case_id, run_id)}/_bulk",
    )

    assert store.get_report_temporal(case_id=case_id, run_id=run_id)["series"][0]["name"] == (
        "external"
    )
    assert store.get_report_logs(case_id=case_id, run_id=run_id)["items"][0]["log_id"] == (
        "external-log"
    )
    assert len(query_client.temporal_calls) == 1
    assert len(query_client.log_calls) == 1

    missing_write_client = RecordingQueryClient()
    missing_write_store = _store(
        tmp_path,
        external_analytics_queries_enabled=True,
        clickhouse_url="http://clickhouse:8123",
    )
    missing_write_store.analytics_query_client = missing_write_client
    missing_case_id, missing_run_id = _seed_case_run(missing_write_store)
    assert missing_write_store.get_report_temporal(
        case_id=missing_case_id, run_id=missing_run_id
    ) is None
    assert missing_write_client.temporal_calls == []

    disabled_client = RecordingQueryClient()
    disabled_store = _store(
        tmp_path,
        external_analytics_queries_enabled=False,
        clickhouse_url="http://clickhouse:8123",
    )
    disabled_store.analytics_query_client = disabled_client
    disabled_case_id, disabled_run_id = _seed_case_run(disabled_store)
    _seed_sink_write(
        disabled_store,
        case_id=disabled_case_id,
        run_id=disabled_run_id,
        sink_name="clickhouse",
        destination="logan.window_aggregates",
    )
    assert disabled_store.get_report_temporal(
        case_id=disabled_case_id, run_id=disabled_run_id
    ) is None
    assert disabled_client.temporal_calls == []


def test_sqlalchemy_failed_clickhouse_query_audits_and_falls_back_to_sql(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="password=hunter2")

    store = _store(
        tmp_path,
        external_analytics_queries_enabled=True,
        clickhouse_url="http://clickhouse:8123/?password=hunter2",
        clickhouse_password="secret-password",
    )
    store.analytics_query_client = AnalyticsQueryClient(
        enabled=True,
        clickhouse_url=store.settings.clickhouse_url,
        clickhouse_database=store.settings.clickhouse_database,
        clickhouse_password=store.settings.clickhouse_password,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    case_id, run_id = _seed_case_run(store)
    _seed_temporal_fanout(store, case_id=case_id, run_id=run_id)
    _seed_sink_write(
        store,
        case_id=case_id,
        run_id=run_id,
        sink_name="clickhouse",
        destination="logan.window_aggregates",
    )

    report = store.get_report_temporal(case_id=case_id, run_id=run_id)

    assert report["series"][0]["name"] == "error"
    assert report["series"][0]["points"][0]["count"] == 7
    audits = store.list_audit_logs(case_id=case_id, action="analytics_query.failed")
    assert len(audits) == 1
    assert audits[0].metadata["report"] == "temporal"
    assert audits[0].metadata["sink_name"] == "clickhouse"
    serialized_audit = json.dumps(audits[0].metadata, sort_keys=True)
    assert "hunter2" not in serialized_audit
    assert "secret-password" not in serialized_audit
    assert "param_case_id" not in serialized_audit


def test_sqlalchemy_failed_opensearch_query_audits_and_falls_back_to_sql_logs(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="token=raw-secret-token")

    store = _store(
        tmp_path,
        external_analytics_queries_enabled=True,
        opensearch_url="http://opensearch:9200",
        opensearch_password="secret-password",
    )
    store.analytics_query_client = AnalyticsQueryClient(
        enabled=True,
        opensearch_url=store.settings.opensearch_url,
        opensearch_password=store.settings.opensearch_password,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    case_id, run_id = _seed_case_run(store)
    _seed_log_fanout(store, case_id=case_id, run_id=run_id)
    _seed_sink_write(
        store,
        case_id=case_id,
        run_id=run_id,
        sink_name="opensearch",
        destination=f"{opensearch_index_name(case_id, run_id)}/_bulk",
    )

    report = store.get_report_logs(case_id=case_id, run_id=run_id)

    assert report["items"][0]["message"] == "sql fallback <SECRET>"
    assert report["total"] == 1
    audits = store.list_audit_logs(case_id=case_id, action="analytics_query.failed")
    assert len(audits) == 1
    assert audits[0].metadata["report"] == "logs"
    assert audits[0].metadata["sink_name"] == "opensearch"
    serialized_audit = json.dumps(audits[0].metadata, sort_keys=True)
    assert "raw-secret-token" not in serialized_audit
    assert "secret-password" not in serialized_audit
