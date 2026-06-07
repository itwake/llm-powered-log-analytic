from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings, settings
from app.services.analytics_sinks import opensearch_index_name


class AnalyticsQueryError(RuntimeError):
    """Raised when an external analytics query cannot be completed safely."""


_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_URL_RE = re.compile(r"https?://[^\s,;]+")
_CLICKHOUSE_GROUP_EXPRESSIONS = {
    "golden_signal": "ifNull(nullIf(golden_signal, ''), 'unknown')",
    "service": "ifNull(nullIf(service, ''), 'unknown')",
    "fault_category": "ifNull(nullIf(fault_category, ''), 'unknown')",
    "template": "ifNull(nullIf(template_id, ''), 'unknown')",
}
_OPENSEARCH_SOURCE_FIELDS = [
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
_OPENSEARCH_SEARCH_FIELDS = [
    "search_text",
    "redacted_message",
    "normalized_message",
    "template_text",
    "entities.*",
]


class AnalyticsQueryClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
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
        self.enabled = enabled
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
    def from_settings(cls, app_settings: Settings = settings) -> AnalyticsQueryClient:
        return cls(
            enabled=app_settings.external_analytics_queries_enabled,
            clickhouse_url=app_settings.clickhouse_url,
            clickhouse_database=app_settings.clickhouse_database,
            clickhouse_username=app_settings.clickhouse_username,
            clickhouse_password=app_settings.clickhouse_password,
            opensearch_url=app_settings.opensearch_url,
            opensearch_username=app_settings.opensearch_username,
            opensearch_password=app_settings.opensearch_password,
            timeout_seconds=app_settings.external_analytics_query_timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def query_temporal(
        self,
        *,
        case_id: str,
        run_id: str,
        group_by: str = "golden_signal",
    ) -> dict[str, object] | None:
        if not self.enabled or not self.clickhouse_url:
            return None
        group_expression = _CLICKHOUSE_GROUP_EXPRESSIONS.get(
            group_by, _CLICKHOUSE_GROUP_EXPRESSIONS["golden_signal"]
        )
        self._validate_clickhouse_identifier(self.clickhouse_database, "database")
        query = _clickhouse_temporal_query(
            database=self.clickhouse_database,
            group_expression=group_expression,
        )
        response = self._request(
            method="POST",
            sink_name="ClickHouse temporal",
            url=self.clickhouse_url,
            auth=self._basic_auth(self.clickhouse_username, self.clickhouse_password),
            params={
                "query": query,
                "param_case_id": case_id,
                "param_run_id": run_id,
            },
            content="",
            headers={"content-type": "text/plain"},
        )
        rows = _parse_clickhouse_rows(response, sink_name="ClickHouse temporal")
        return _temporal_report(rows)

    def query_logs(
        self,
        *,
        case_id: str,
        run_id: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        q: str | None = None,
        service: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, object] | None:
        if not self.enabled or not self.opensearch_url:
            return None
        index_name = opensearch_index_name(case_id, run_id)
        body = _opensearch_logs_body(
            case_id=case_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
            q=q,
            service=service,
            limit=limit,
            offset=offset,
        )
        response = self._request(
            method="POST",
            sink_name="OpenSearch logs",
            url=f"{self.opensearch_url}/{index_name}/_search",
            auth=self._basic_auth(self.opensearch_username, self.opensearch_password),
            content=json.dumps(body, separators=(",", ":"), sort_keys=True),
            headers={"content-type": "application/json"},
        )
        payload = _json_payload(response, sink_name="OpenSearch logs")
        return _logs_report(payload)

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
    ) -> httpx.Response:
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
            raise AnalyticsQueryError(
                f"{sink_name} query failed with transport error: {exc.__class__.__name__}"
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise AnalyticsQueryError(
                f"{sink_name} query failed with HTTP {response.status_code} at "
                f"{_safe_url(response.request.url)}"
            )
        return response

    def _basic_auth(
        self, username: str | None, password: str | None
    ) -> httpx.BasicAuth | None:
        if not username and not password:
            return None
        return httpx.BasicAuth(username or "", password or "")

    def _validate_clickhouse_identifier(self, value: str, kind: str) -> None:
        if not _SAFE_IDENTIFIER_RE.match(value):
            raise AnalyticsQueryError(f"ClickHouse {kind} name is not a safe identifier")


def _clickhouse_temporal_query(*, database: str, group_expression: str) -> str:
    return (
        "SELECT "
        "window_size_seconds, "
        "name, "
        "window_start, "
        "sum(count) AS aggregate_count "
        "FROM ("
        "SELECT "
        "window_size_seconds, "
        f"{group_expression} AS name, "
        "window_start, "
        "count "
        f"FROM {database}.window_aggregates "
        "WHERE case_id = {case_id:String} "
        "AND analysis_run_id = {run_id:String}"
        ") "
        "GROUP BY window_size_seconds, name, window_start "
        "ORDER BY name ASC, window_start ASC "
        "FORMAT JSON"
    )


def _opensearch_logs_body(
    *,
    case_id: str,
    run_id: str,
    window_start: datetime | None,
    window_end: datetime | None,
    q: str | None,
    service: str | None,
    limit: int,
    offset: int,
) -> dict[str, object]:
    filters: list[dict[str, object]] = [
        {"term": {"case_id": case_id}},
        {"term": {"analysis_run_id": run_id}},
    ]
    if service:
        filters.append({"term": {"service": service}})
    range_filter: dict[str, str] = {}
    if window_start:
        range_filter["gte"] = _iso(window_start)
    if window_end:
        range_filter["lte"] = _iso(window_end)
    if range_filter:
        filters.append({"range": {"timestamp": range_filter}})

    bool_query: dict[str, object] = {"filter": filters}
    if q and q.strip():
        bool_query["must"] = [
            {
                "simple_query_string": {
                    "query": q,
                    "fields": _OPENSEARCH_SEARCH_FIELDS,
                    "default_operator": "and",
                }
            }
        ]

    return {
        "track_total_hits": True,
        "from": max(0, offset),
        "size": max(0, limit),
        "_source": _OPENSEARCH_SOURCE_FIELDS,
        "query": {"bool": bool_query},
        "sort": [
            {"timestamp": {"order": "asc", "missing": "_last"}},
            {"file_path": {"order": "asc"}},
            {"line_number": {"order": "asc"}},
            {"log_id": {"order": "asc"}},
        ],
        "aggs": {
            "service": {"terms": {"field": "service", "size": 100, "missing": "unknown"}},
            "golden_signal": {
                "terms": {"field": "golden_signal", "size": 100, "missing": "unknown"}
            },
            "fault_category": {"terms": {"field": "fault_categories", "size": 100}},
        },
    }


def _parse_clickhouse_rows(response: httpx.Response, *, sink_name: str) -> list[dict[str, Any]]:
    text = response.text.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except ValueError:
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise AnalyticsQueryError(f"{sink_name} returned invalid JSONEachRow") from exc
            if isinstance(row, dict):
                rows.append(row)
        return rows

    if isinstance(payload, dict):
        data = payload.get("data", [])
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _json_payload(response: httpx.Response, *, sink_name: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AnalyticsQueryError(f"{sink_name} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AnalyticsQueryError(f"{sink_name} returned an unexpected JSON shape")
    return payload


def _temporal_report(rows: list[dict[str, Any]]) -> dict[str, object] | None:
    if not rows:
        return None
    grouped: dict[str, dict[str, int]] = {}
    window_size_seconds = _int_value(rows[0].get("window_size_seconds"))
    for row in rows:
        name = str(row.get("name") or "unknown")
        window_start = _external_datetime(row.get("window_start"))
        if window_start is None:
            continue
        count = _int_value(row.get("aggregate_count", row.get("count")))
        points = grouped.setdefault(name, {})
        points[window_start] = points.get(window_start, 0) + count
        if not window_size_seconds:
            window_size_seconds = _int_value(row.get("window_size_seconds"))

    if not grouped:
        return None
    return {
        "window_size_seconds": window_size_seconds,
        "series": [
            {
                "name": name,
                "points": [
                    {"window_start": window_start, "count": count}
                    for window_start, count in sorted(points.items())
                ],
            }
            for name, points in sorted(grouped.items())
        ],
    }


def _logs_report(payload: dict[str, Any]) -> dict[str, object]:
    hits_payload = payload.get("hits") if isinstance(payload, dict) else None
    hits = hits_payload.get("hits", []) if isinstance(hits_payload, dict) else []
    total_payload = hits_payload.get("total", 0) if isinstance(hits_payload, dict) else 0
    items = []
    hit_items = hits if isinstance(hits, list) else []
    for hit in hit_items:
        source = hit.get("_source", {}) if isinstance(hit, dict) else {}
        if not isinstance(source, dict):
            continue
        items.append(
            {
                "log_id": source.get("log_id"),
                "timestamp": _external_datetime(source.get("timestamp")),
                "level": source.get("level"),
                "service": source.get("service"),
                "file_path": source.get("file_path"),
                "line_number": _int_value(source.get("line_number")),
                "line_numbers": _int_list(source.get("line_numbers"), source.get("line_number")),
                "message": source.get("redacted_message") or "",
                "template_id": source.get("template_id"),
                "template_text": source.get("template_text"),
                "golden_signal": source.get("golden_signal") or "unknown",
                "fault_categories": _str_list(source.get("fault_categories")),
                "entities": _entities(source.get("entities")),
            }
        )

    return {
        "items": items,
        "total": _total_value(total_payload),
        "facets": {
            "service": _terms(payload, "service"),
            "golden_signal": _terms(payload, "golden_signal"),
            "fault_category": _terms(payload, "fault_category"),
        },
    }


def _terms(payload: dict[str, Any], name: str) -> list[dict[str, object]]:
    aggregations = payload.get("aggregations")
    aggregate = aggregations.get(name) if isinstance(aggregations, dict) else None
    buckets = aggregate.get("buckets", []) if isinstance(aggregate, dict) else []
    terms: list[dict[str, object]] = []
    bucket_items = buckets if isinstance(buckets, list) else []
    for bucket in bucket_items:
        if not isinstance(bucket, dict):
            continue
        key = bucket.get("key_as_string", bucket.get("key"))
        terms.append(
            {
                "value": str(key if key is not None else "unknown"),
                "count": _int_value(bucket.get("doc_count")),
            }
        )
    return terms


def _total_value(value: Any) -> int:
    if isinstance(value, dict):
        return _int_value(value.get("value"))
    return _int_value(value)


def _int_value(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _int_list(value: Any, fallback: Any) -> list[int]:
    values = value if isinstance(value, list) else [value] if value is not None else []
    parsed = [_int_value(item) for item in values]
    parsed = [item for item in parsed if item]
    if parsed:
        return parsed
    fallback_value = _int_value(fallback)
    return [fallback_value] if fallback_value else []


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]


def _entities(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    entities: dict[str, list[str]] = {}
    for key, raw_values in value.items():
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        cleaned = [str(item) for item in values if item is not None]
        if cleaned:
            entities[str(key)] = cleaned
    return entities


def _external_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        if " " in normalized and "T" not in normalized:
            normalized = normalized.replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return text
    else:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()


def _safe_url(url: httpx.URL | str) -> str:
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def sanitize_analytics_query_error(error: object) -> str:
    return _URL_RE.sub(lambda match: _safe_url(match.group(0)), str(error))
