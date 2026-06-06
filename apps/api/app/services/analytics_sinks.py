from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
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


_SAFE_INDEX_RE = re.compile(r"[^a-z0-9._-]+")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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

        if self.clickhouse_url:
            log_rows = build_clickhouse_enriched_log_rows(result)
            window_rows = build_clickhouse_window_rows(result)
            self._post_clickhouse_json_each_row("enriched_log_lines", log_rows)
            self._post_clickhouse_json_each_row("window_aggregates", window_rows)
            clickhouse_log_rows = len(log_rows)
            clickhouse_window_rows = len(window_rows)

        if self.opensearch_url:
            documents = build_opensearch_log_documents(result)
            if documents:
                self._post_opensearch_bulk(
                    index_name=opensearch_index_name(result.case_id, result.analysis_run_id),
                    documents=documents,
                )
            opensearch_documents = len(documents)

        return AnalyticsSinkPublishResult(
            clickhouse_enriched_log_rows=clickhouse_log_rows,
            clickhouse_window_rows=clickhouse_window_rows,
            opensearch_documents=opensearch_documents,
        )

    def _post_clickhouse_json_each_row(
        self, table_name: str, rows: list[dict[str, object]]
    ) -> None:
        if not self.clickhouse_url:
            return
        if not _SAFE_IDENTIFIER_RE.match(self.clickhouse_database):
            raise AnalyticsSinkError("ClickHouse database name is not a safe identifier")
        if not _SAFE_IDENTIFIER_RE.match(table_name):
            raise AnalyticsSinkError("ClickHouse table name is not a safe identifier")

        query = f"INSERT INTO {self.clickhouse_database}.{table_name} FORMAT JSONEachRow"
        self._post(
            sink_name=f"ClickHouse {table_name}",
            url=self.clickhouse_url,
            auth=self._basic_auth(self.clickhouse_username, self.clickhouse_password),
            params={"query": query},
            content=_ndjson(rows),
            headers={"content-type": "application/x-ndjson"},
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
        try:
            response = self.http_client.post(
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


def _safe_url(url: httpx.URL) -> str:
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))
