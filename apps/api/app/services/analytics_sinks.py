from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
from logan_workers.models import AnalysisResult, EvidenceRef

from app.config import Settings, settings


class AnalyticsSinkError(RuntimeError):
    """Raised when an external analytics sink rejects or cannot receive a publish."""


@dataclass(frozen=True)
class AnalyticsSinkPublishResult:
    clickhouse_enriched_log_rows: int = 0
    clickhouse_window_rows: int = 0
    opensearch_documents: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class AnalyticsSinkWriteOperation:
    case_id: str
    analysis_run_id: str
    sink_name: str
    destination: str
    idempotency_key: str
    payload_hash: str
    row_count: int
    _publish: Callable[[], None] = field(repr=False, compare=False)

    def execute(self) -> None:
        self._publish()


_SAFE_INDEX_RE = re.compile(r"[^a-z0-9._-]+")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_CLICKHOUSE_TABLE_SCHEMAS: dict[str, str] = {
    "enriched_log_lines": """
        case_id String,
        analysis_run_id String,
        log_id String,
        raw_log_id String,
        file_id String,
        timestamp Nullable(DateTime64(3, 'UTC')),
        timestamp_quality String,
        level Nullable(String),
        service Nullable(String),
        file_path String,
        line_number UInt64,
        line_numbers Array(UInt64),
        redacted_message String,
        normalized_message String,
        template_id Nullable(String),
        template_text Nullable(String),
        golden_signal Nullable(String),
        fault_categories Array(String),
        entities Map(String, Array(String)),
        severity_score Float64,
        confidence Float64,
        parser_name Nullable(String),
        parser_confidence Float64,
        ingestion_order UInt64
    """,
    "window_aggregates": """
        case_id String,
        analysis_run_id String,
        window_start DateTime64(3, 'UTC'),
        window_end DateTime64(3, 'UTC'),
        window_size_seconds UInt32,
        template_id Nullable(String),
        service Nullable(String),
        golden_signal String,
        fault_category Nullable(String),
        count UInt64
    """,
}
_CLICKHOUSE_TABLE_ORDER_BY: dict[str, str] = {
    "enriched_log_lines": "(case_id, analysis_run_id, ingestion_order, log_id)",
    "window_aggregates": "(case_id, analysis_run_id, window_start, ifNull(template_id, ''))",
}

_OPENSEARCH_INDEX_BODY: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "index": {"mapping": {"total_fields": {"limit": 1000}}},
    },
    "mappings": {
        "dynamic": True,
        "properties": {
            "case_id": {"type": "keyword"},
            "analysis_run_id": {"type": "keyword"},
            "log_id": {"type": "keyword"},
            "file_id": {"type": "keyword"},
            "timestamp": {"type": "date"},
            "timestamp_quality": {"type": "keyword"},
            "level": {"type": "keyword"},
            "service": {"type": "keyword"},
            "file_path": {"type": "keyword"},
            "line_number": {"type": "integer"},
            "line_numbers": {"type": "integer"},
            "redacted_message": {"type": "text"},
            "normalized_message": {"type": "text"},
            "search_text": {"type": "text"},
            "template_id": {"type": "keyword"},
            "template_text": {"type": "text"},
            "golden_signal": {"type": "keyword"},
            "fault_categories": {"type": "keyword"},
            "entities": {"type": "object", "enabled": True},
            "severity_score": {"type": "float"},
            "confidence": {"type": "float"},
            "ingestion_order": {"type": "integer"},
            "evidence_refs": {
                "type": "nested",
                "properties": {
                    "case_id": {"type": "keyword"},
                    "analysis_run_id": {"type": "keyword"},
                    "template_id": {"type": "keyword"},
                    "log_id": {"type": "keyword"},
                    "file_path": {"type": "keyword"},
                    "line_number": {"type": "integer"},
                    "timestamp": {"type": "date"},
                },
            },
        },
    },
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _evidence_ref(ref: EvidenceRef) -> dict[str, object]:
    return {
        "case_id": ref.case_id,
        "analysis_run_id": ref.analysis_run_id,
        "template_id": ref.template_id,
        "log_id": ref.log_id,
        "file_path": ref.file_path,
        "line_number": ref.line_number,
        "timestamp": _iso(ref.timestamp),
    }


def opensearch_index_name(case_id: str, analysis_run_id: str) -> str:
    raw = f"logan-logs-{case_id}-{analysis_run_id}".lower()
    sanitized = _SAFE_INDEX_RE.sub("-", raw)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-._")
    return sanitized or "logan-logs-unknown"


def build_clickhouse_enriched_log_rows(result: AnalysisResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in result.normalized_logs:
        rows.append(
            {
                "case_id": line.case_id,
                "analysis_run_id": line.analysis_run_id,
                "log_id": line.log_id,
                "raw_log_id": line.raw_log_id,
                "file_id": line.file_id,
                "timestamp": _iso(line.timestamp),
                "timestamp_quality": line.timestamp_quality,
                "level": line.level,
                "service": line.service,
                "file_path": line.file_path,
                "line_number": line.line_number,
                "line_numbers": list(line.line_numbers),
                "redacted_message": line.redacted_message,
                "normalized_message": line.normalized_message,
                "template_id": line.template_id,
                "template_text": line.template_text,
                "golden_signal": line.golden_signal,
                "fault_categories": list(line.fault_categories),
                "entities": {
                    key: list(values)
                    for key, values in line.entities.items()
                    if values
                },
                "severity_score": line.severity_score,
                "confidence": line.confidence,
                "parser_name": line.parser_name,
                "parser_confidence": line.parser_confidence,
                "ingestion_order": line.ingestion_order,
            }
        )
    return rows


def build_clickhouse_window_rows(result: AnalysisResult) -> list[dict[str, object]]:
    return [
        {
            "case_id": result.case_id,
            "analysis_run_id": result.analysis_run_id,
            "window_start": _iso(aggregate.window_start),
            "window_end": _iso(aggregate.window_end),
            "window_size_seconds": aggregate.window_size_seconds,
            "template_id": aggregate.template_id,
            "service": aggregate.service,
            "golden_signal": aggregate.golden_signal,
            "fault_category": aggregate.fault_category,
            "count": aggregate.count,
        }
        for aggregate in result.temporal
    ]


def build_opensearch_log_documents(result: AnalysisResult) -> list[dict[str, object]]:
    documents: list[dict[str, object]] = []
    for line in result.normalized_logs:
        search_text = " ".join(
            part
            for part in (line.redacted_message, line.normalized_message, line.template_text)
            if part
        )
        documents.append(
            {
                "case_id": line.case_id,
                "analysis_run_id": line.analysis_run_id,
                "log_id": line.log_id,
                "file_id": line.file_id,
                "timestamp": _iso(line.timestamp),
                "timestamp_quality": line.timestamp_quality,
                "level": line.level,
                "service": line.service,
                "file_path": line.file_path,
                "line_number": line.line_number,
                "line_numbers": list(line.line_numbers),
                "redacted_message": line.redacted_message,
                "normalized_message": line.normalized_message,
                "search_text": search_text,
                "template_id": line.template_id,
                "template_text": line.template_text,
                "golden_signal": line.golden_signal,
                "fault_categories": list(line.fault_categories),
                "entities": {
                    key: list(values)
                    for key, values in line.entities.items()
                    if values
                },
                "severity_score": line.severity_score,
                "confidence": line.confidence,
                "evidence_refs": [_evidence_ref(line.evidence_ref())],
                "ingestion_order": line.ingestion_order,
            }
        )
    return documents


class AnalyticsSinkPublisher:
    def __init__(
        self,
        *,
        clickhouse_url: str | None = None,
        clickhouse_database: str = "logan",
        clickhouse_username: str | None = None,
        clickhouse_password: str | None = None,
        opensearch_url: str | None = None,
        opensearch_username: str | None = None,
        opensearch_password: str | None = None,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.clickhouse_url = clickhouse_url.rstrip("/") if clickhouse_url else None
        self.clickhouse_database = clickhouse_database
        self.clickhouse_username = clickhouse_username
        self.clickhouse_password = clickhouse_password
        self.opensearch_url = opensearch_url.rstrip("/") if opensearch_url else None
        self.opensearch_username = opensearch_username
        self.opensearch_password = opensearch_password
        self.http_client = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None

    @classmethod
    def from_settings(cls, app_settings: Settings = settings) -> AnalyticsSinkPublisher:
        return cls(
            clickhouse_url=app_settings.clickhouse_url,
            clickhouse_database=app_settings.clickhouse_database,
            clickhouse_username=app_settings.clickhouse_username,
            clickhouse_password=app_settings.clickhouse_password,
            opensearch_url=app_settings.opensearch_url,
            opensearch_username=app_settings.opensearch_username,
            opensearch_password=app_settings.opensearch_password,
        )

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def publish(self, result: AnalysisResult) -> AnalyticsSinkPublishResult:
        clickhouse_log_rows = 0
        clickhouse_window_rows = 0
        opensearch_documents = 0

        for operation in self.publish_operations(result):
            operation.execute()
            if operation.sink_name == "clickhouse":
                if operation.destination.endswith(".enriched_log_lines"):
                    clickhouse_log_rows += operation.row_count
                elif operation.destination.endswith(".window_aggregates"):
                    clickhouse_window_rows += operation.row_count
            elif operation.sink_name == "opensearch":
                opensearch_documents += operation.row_count

        return AnalyticsSinkPublishResult(
            clickhouse_enriched_log_rows=clickhouse_log_rows,
            clickhouse_window_rows=clickhouse_window_rows,
            opensearch_documents=opensearch_documents,
        )

    def publish_operations(self, result: AnalysisResult) -> list[AnalyticsSinkWriteOperation]:
        operations: list[AnalyticsSinkWriteOperation] = []
        clickhouse_lifecycle_ensured = False

        def ensure_clickhouse_once() -> None:
            nonlocal clickhouse_lifecycle_ensured
            if not clickhouse_lifecycle_ensured:
                self._ensure_clickhouse_lifecycle()
                clickhouse_lifecycle_ensured = True

        if self.clickhouse_url:
            clickhouse_targets = [
                ("enriched_log_lines", build_clickhouse_enriched_log_rows(result)),
                ("window_aggregates", build_clickhouse_window_rows(result)),
            ]
            for table_name, rows in clickhouse_targets:
                destination = f"{self.clickhouse_database}.{table_name}"

                def publish_clickhouse_table(
                    table_name: str = table_name, rows: list[dict[str, object]] = rows
                ) -> None:
                    ensure_clickhouse_once()
                    self._post_clickhouse_json_each_row(table_name, rows)

                operations.append(
                    _write_operation(
                        result=result,
                        sink_name="clickhouse",
                        destination=destination,
                        row_count=len(rows),
                        payload=rows,
                        publish=publish_clickhouse_table,
                    )
                )

        if self.opensearch_url:
            documents = build_opensearch_log_documents(result)
            if documents:
                index_name = opensearch_index_name(result.case_id, result.analysis_run_id)
                destination = f"{index_name}/_bulk"

                def publish_opensearch_bulk(
                    index_name: str = index_name,
                    documents: list[dict[str, object]] = documents,
                ) -> None:
                    self._ensure_opensearch_index(index_name)
                    self._post_opensearch_bulk(index_name=index_name, documents=documents)

                operations.append(
                    _write_operation(
                        result=result,
                        sink_name="opensearch",
                        destination=destination,
                        row_count=len(documents),
                        payload=documents,
                        publish=publish_opensearch_bulk,
                    )
                )

        return operations

    def _ensure_clickhouse_lifecycle(self) -> None:
        if not self.clickhouse_url:
            return
        self._validate_clickhouse_identifier(self.clickhouse_database, "database")
        for table_name in _CLICKHOUSE_TABLE_SCHEMAS:
            self._validate_clickhouse_identifier(table_name, "table")

        self._post_clickhouse_query(
            sink_name="ClickHouse database lifecycle",
            query=f"CREATE DATABASE IF NOT EXISTS {self.clickhouse_database}",
        )
        for table_name in _CLICKHOUSE_TABLE_SCHEMAS:
            self._post_clickhouse_query(
                sink_name=f"ClickHouse {table_name} lifecycle",
                query=self._clickhouse_create_table_query(table_name),
            )

    def _clickhouse_create_table_query(self, table_name: str) -> str:
        self._validate_clickhouse_identifier(self.clickhouse_database, "database")
        self._validate_clickhouse_identifier(table_name, "table")
        schema = " ".join(_CLICKHOUSE_TABLE_SCHEMAS[table_name].split())
        order_by = _CLICKHOUSE_TABLE_ORDER_BY[table_name]
        return (
            f"CREATE TABLE IF NOT EXISTS {self.clickhouse_database}.{table_name} "
            f"({schema}) ENGINE = MergeTree ORDER BY {order_by}"
        )

    def _post_clickhouse_query(self, *, sink_name: str, query: str) -> None:
        if not self.clickhouse_url:
            return
        self._post(
            sink_name=sink_name,
            url=self.clickhouse_url,
            auth=self._basic_auth(self.clickhouse_username, self.clickhouse_password),
            params={"query": query},
            content="",
            headers={"content-type": "text/plain"},
        )

    def _validate_clickhouse_identifier(self, value: str, kind: str) -> None:
        if not _SAFE_IDENTIFIER_RE.match(value):
            raise AnalyticsSinkError(f"ClickHouse {kind} name is not a safe identifier")

    def _post_clickhouse_json_each_row(
        self, table_name: str, rows: list[dict[str, object]]
    ) -> None:
        if not self.clickhouse_url:
            return
        self._validate_clickhouse_identifier(self.clickhouse_database, "database")
        self._validate_clickhouse_identifier(table_name, "table")

        query = f"INSERT INTO {self.clickhouse_database}.{table_name} FORMAT JSONEachRow"
        self._post(
            sink_name=f"ClickHouse {table_name}",
            url=self.clickhouse_url,
            auth=self._basic_auth(self.clickhouse_username, self.clickhouse_password),
            params={"query": query},
            content=_ndjson(rows),
            headers={"content-type": "application/x-ndjson"},
        )

    def _ensure_opensearch_index(self, index_name: str) -> None:
        if not self.opensearch_url:
            return
        self._request(
            method="PUT",
            sink_name="OpenSearch index lifecycle",
            url=f"{self.opensearch_url}/{index_name}",
            auth=self._basic_auth(self.opensearch_username, self.opensearch_password),
            content=json.dumps(_OPENSEARCH_INDEX_BODY, separators=(",", ":"), sort_keys=True),
            headers={"content-type": "application/json"},
            allow_resource_already_exists=True,
        )

    def _post_opensearch_bulk(
        self, *, index_name: str, documents: list[dict[str, object]]
    ) -> None:
        if not self.opensearch_url:
            return
        lines: list[dict[str, Any]] = []
        for document in documents:
            lines.append({"index": {"_index": index_name, "_id": document["log_id"]}})
            lines.append(document)
        self._post(
            sink_name="OpenSearch bulk",
            url=f"{self.opensearch_url}/_bulk",
            auth=self._basic_auth(self.opensearch_username, self.opensearch_password),
            content=_ndjson(lines),
            headers={"content-type": "application/x-ndjson"},
        )

    def _post(
        self,
        *,
        sink_name: str,
        url: str,
        auth: httpx.BasicAuth | None,
        content: str,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
    ) -> None:
        self._request(
            method="POST",
            sink_name=sink_name,
            url=url,
            auth=auth,
            content=content,
            headers=headers,
            params=params,
        )

    def _request(
        self,
        *,
        method: str,
        sink_name: str,
        url: str,
        auth: httpx.BasicAuth | None,
        content: str,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        allow_resource_already_exists: bool = False,
    ) -> None:
        try:
            response = self.http_client.request(
                method,
                url,
                auth=auth,
                content=content,
                headers=headers,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise AnalyticsSinkError(
                f"{sink_name} publish failed with transport error: {exc.__class__.__name__}"
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            if allow_resource_already_exists and _resource_already_exists(response):
                return
            raise AnalyticsSinkError(
                f"{sink_name} publish failed with HTTP {response.status_code} at "
                f"{_safe_url(response.request.url)}"
            )

    def _basic_auth(
        self, username: str | None, password: str | None
    ) -> httpx.BasicAuth | None:
        if not username and not password:
            return None
        return httpx.BasicAuth(username or "", password or "")


def _ndjson(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    encoded = (json.dumps(row, separators=(",", ":"), sort_keys=True) for row in rows)
    return "\n".join(encoded) + "\n"


def _write_operation(
    *,
    result: AnalysisResult,
    sink_name: str,
    destination: str,
    row_count: int,
    payload: Any,
    publish: Callable[[], None],
) -> AnalyticsSinkWriteOperation:
    payload_hash = _payload_hash(payload)
    idempotency_key = _idempotency_key(
        case_id=result.case_id,
        analysis_run_id=result.analysis_run_id,
        sink_name=sink_name,
        destination=destination,
        payload_hash=payload_hash,
    )
    return AnalyticsSinkWriteOperation(
        case_id=result.case_id,
        analysis_run_id=result.analysis_run_id,
        sink_name=sink_name,
        destination=destination,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        row_count=row_count,
        _publish=publish,
    )


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _idempotency_key(
    *,
    case_id: str,
    analysis_run_id: str,
    sink_name: str,
    destination: str,
    payload_hash: str,
) -> str:
    material = json.dumps(
        {
            "analysis_run_id": analysis_run_id,
            "case_id": case_id,
            "destination": destination,
            "payload_hash": payload_hash,
            "sink_name": sink_name,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"analytics-sink:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def _resource_already_exists(response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return "resource_already_exists_exception" in response.text
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, str):
        return "resource_already_exists_exception" in error
    if not isinstance(error, dict):
        return False
    if error.get("type") == "resource_already_exists_exception":
        return True
    root_causes = error.get("root_cause")
    if isinstance(root_causes, list):
        return any(
            isinstance(item, dict)
            and item.get("type") == "resource_already_exists_exception"
            for item in root_causes
        )
    return False


def _safe_url(url: httpx.URL) -> str:
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))
