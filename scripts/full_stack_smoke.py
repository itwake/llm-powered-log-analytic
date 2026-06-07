#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import boto3
import httpx
from botocore.config import Config
from sqlalchemy import create_engine, text


REPO_ROOT = Path(__file__).resolve().parents[1]
for package_root in (REPO_ROOT / "apps" / "api", REPO_ROOT / "apps" / "workers"):
    package_root_text = str(package_root)
    if package_root_text not in sys.path:
        sys.path.insert(0, package_root_text)

from app.services.analytics_sinks import opensearch_index_name


FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "logs" / "checkout_incident"
PIPELINE_STEPS = {
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
}
FAKE_SECRET_TOKEN = "fullstacksmokesecretvalue1234567890"
FAKE_PASSWORD = "hunter2"
FORBIDDEN_SAFE_SURFACE_PATTERNS = (
    re.compile(re.escape(FAKE_SECRET_TOKEN), re.IGNORECASE),
    re.compile(re.escape(FAKE_PASSWORD), re.IGNORECASE),
    re.compile(r"X-Amz-[A-Za-z-]+", re.IGNORECASE),
    re.compile(r"AWSAccessKeyId", re.IGNORECASE),
    re.compile(r"Signature=", re.IGNORECASE),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"/tmp/logan-analysis-inputs", re.IGNORECASE),
    re.compile(r"\.logan/analysis-inputs", re.IGNORECASE),
)


class SmokeFailure(RuntimeError):
    pass


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _log(message: str) -> None:
    print(f"[full-stack-smoke] {message}", flush=True)


def _redact_error(message: object) -> str:
    text_value = str(message)
    for secret in (
        _env("LOGAN_FULL_STACK_S3_SECRET_KEY", ""),
        os.getenv("LOGAN_GITHUB_COPILOT_TOKEN", ""),
        os.getenv("LOGAN_GITHUB_SOURCE_TOKEN", ""),
        FAKE_SECRET_TOKEN,
        FAKE_PASSWORD,
    ):
        if secret:
            text_value = text_value.replace(secret, "<redacted>")
    text_value = re.sub(r"([?&](?:X-Amz-[^=]+|Signature|token|password|secret)=)[^&\s]+", r"\1<redacted>", text_value, flags=re.IGNORECASE)
    return text_value


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _assert_safe_surface(name: str, payload: Any) -> None:
    serialized = _json(payload)
    for pattern in FORBIDDEN_SAFE_SURFACE_PATTERNS:
        match = pattern.search(serialized)
        if match:
            raise SmokeFailure(f"{name} leaked forbidden material matching {pattern.pattern}")


def _retry(
    name: str,
    action: Callable[[], Any],
    *,
    timeout_seconds: float = 60,
    interval_seconds: float = 2,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - smoke retries external services.
            last_error = exc
            time.sleep(interval_seconds)
    detail = _redact_error(last_error) if last_error else "timed out"
    raise SmokeFailure(f"{name} did not become ready: {detail}")


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected_status: int = 200,
    **kwargs: Any,
) -> dict[str, Any]:
    response = client.request(method, path, **kwargs)
    if response.status_code != expected_status:
        raise SmokeFailure(
            f"{method} {path} returned HTTP {response.status_code}: "
            f"{_redact_error(response.text[:500])}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SmokeFailure(f"{method} {path} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{method} {path} returned a non-object JSON payload")
    return payload


def _api_base_url() -> str:
    return _env("LOGAN_FULL_STACK_API_BASE_URL", "http://localhost:8000").rstrip("/")


def _host_is_local(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host in {"127.0.0.1", "localhost", "::1"}


def _default_s3_endpoint(api_base_url: str) -> str:
    if os.getenv("LOGAN_FULL_STACK_S3_ENDPOINT"):
        return os.environ["LOGAN_FULL_STACK_S3_ENDPOINT"].rstrip("/")
    return "http://localhost:9000" if _host_is_local(api_base_url) else "http://minio:9000"


def _upload_public_endpoint(api_base_url: str) -> str | None:
    explicit = os.getenv("LOGAN_FULL_STACK_S3_PUBLIC_ENDPOINT")
    if explicit:
        return explicit.rstrip("/")
    return "http://localhost:9000" if _host_is_local(api_base_url) else None


def _rewrite_upload_url(upload_url: str, public_endpoint: str | None) -> str:
    if not public_endpoint:
        return upload_url
    parsed_upload = urlsplit(upload_url)
    parsed_public = urlsplit(public_endpoint)
    return urlunsplit(
        (
            parsed_public.scheme,
            parsed_public.netloc,
            parsed_upload.path,
            parsed_upload.query,
            parsed_upload.fragment,
        )
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _s3_client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=_env("LOGAN_FULL_STACK_S3_ACCESS_KEY", "logan"),
        aws_secret_access_key=_env("LOGAN_FULL_STACK_S3_SECRET_KEY", "logan-secret"),
        region_name=_env("LOGAN_FULL_STACK_S3_REGION", "us-east-1"),
        config=Config(s3={"addressing_style": "path"}),
    )


def _safe_upload_key(case_id: str, file_id: str, filename: str) -> str:
    return f"cases/{case_id}/uploads/{file_id}/{Path(filename).name}"


def _fixture_payloads() -> list[tuple[str, bytes]]:
    if not FIXTURE_DIR.is_dir():
        raise SmokeFailure(f"fixture directory missing: {FIXTURE_DIR}")
    payloads: list[tuple[str, bytes]] = []
    for path in sorted(FIXTURE_DIR.glob("*.log")):
        content = path.read_bytes()
        if path.name == "gateway.log":
            content += (
                b"\n2026-06-06T10:09:59Z ERROR gateway-service "
                b"request failed source_token="
                + FAKE_SECRET_TOKEN.encode("utf-8")
                + b" password="
                + FAKE_PASSWORD.encode("utf-8")
                + b"\n"
            )
        payloads.append((path.name, content))
    _assert(payloads, "no fixture log payloads were found")
    return payloads


def _wait_for_api(client: httpx.Client) -> None:
    def check() -> None:
        response = client.get("/healthz")
        if response.status_code != 200 or response.json().get("status") != "ok":
            raise RuntimeError(f"HTTP {response.status_code}")

    _retry("api", check, timeout_seconds=120, interval_seconds=2)


def _wait_for_run(client: httpx.Client, case_id: str, run_id: str) -> dict[str, Any]:
    timeout_seconds = float(_env("LOGAN_FULL_STACK_RUN_TIMEOUT_SECONDS", "420"))
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        payload = _request_json(
            client,
            "GET",
            f"/api/cases/{case_id}/analysis-runs/{run_id}",
        )
        last_payload = payload
        if payload.get("status") == "completed":
            return payload
        if payload.get("status") == "failed":
            raise SmokeFailure(
                "analysis run failed: "
                f"{_redact_error(payload.get('error_message') or payload)}"
            )
        time.sleep(2)
    raise SmokeFailure(f"analysis run timed out: {_redact_error(last_payload)}")


def _upload_fixtures(
    client: httpx.Client,
    *,
    case_id: str,
    s3_endpoint: str,
    upload_public_endpoint: str | None,
) -> list[str]:
    bucket = _env("LOGAN_FULL_STACK_S3_BUCKET", "logan")
    s3 = _s3_client(s3_endpoint)
    file_ids: list[str] = []
    for filename, content in _fixture_payloads():
        upload = _request_json(
            client,
            "POST",
            f"/api/cases/{case_id}/uploads",
            json={
                "filename": filename,
                "content_type": "text/plain",
                "size_bytes": len(content),
            },
        )
        _assert(upload.get("upload_backend") in {"s3", "minio"}, "upload did not use S3/MinIO")
        _assert(upload.get("upload_mode") == "single", "smoke expected a single-part upload")
        _assert(upload.get("object_uri") in {None, ""}, "presigned upload exposed object_uri")
        file_id = str(upload["file_id"])
        upload_url = _rewrite_upload_url(str(upload["upload_url"]), upload_public_endpoint)
        upload_headers = {
            str(key): str(value)
            for key, value in (upload.get("upload_headers") or {}).items()
        }
        put = httpx.put(upload_url, content=content, headers=upload_headers, timeout=60)
        if put.status_code not in {200, 201}:
            raise SmokeFailure(
                f"MinIO upload for {filename} returned HTTP {put.status_code}: "
                f"{_redact_error(put.text[:300])}"
            )
        key = _safe_upload_key(case_id, file_id, filename)
        head = s3.head_object(Bucket=bucket, Key=key)
        _assert(int(head.get("ContentLength", -1)) == len(content), "MinIO object size mismatch")
        completed = _request_json(
            client,
            "POST",
            f"/api/cases/{case_id}/uploads/{file_id}/complete",
            json={"sha256": _sha256(content)},
        )
        _assert(completed.get("status") == "completed", "upload was not completed")
        _assert(completed.get("file_id") == file_id, "completed upload id mismatch")
        file_ids.append(file_id)
    return file_ids


def _clickhouse_count(url: str, query: str, *, case_id: str, run_id: str) -> int:
    def call() -> int:
        response = httpx.post(
            url,
            params={
                "query": query,
                "param_case_id": case_id,
                "param_run_id": run_id,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("empty ClickHouse response")
        row = rows[0]
        if not isinstance(row, dict):
            raise RuntimeError("unexpected ClickHouse row")
        value = row.get("count")
        return int(value)

    return int(_retry("clickhouse query", call, timeout_seconds=90, interval_seconds=3))


def _safe_clickhouse_identifier(value: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise SmokeFailure("ClickHouse database name is not a safe identifier")
    return value


def _opensearch_count(url: str, *, case_id: str, run_id: str) -> int:
    index = opensearch_index_name(case_id, run_id)

    def call() -> int:
        httpx.post(f"{url.rstrip('/')}/{index}/_refresh", timeout=10).raise_for_status()
        response = httpx.post(
            f"{url.rstrip('/')}/{index}/_count",
            json={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"case_id": case_id}},
                            {"term": {"analysis_run_id": run_id}},
                        ]
                    }
                }
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return int(payload.get("count", 0))

    return int(_retry("opensearch query", call, timeout_seconds=90, interval_seconds=3))


def _database_checks(database_url: str, *, case_id: str, run_id: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            sink_rows = connection.execute(
                text(
                    """
                    SELECT sink_name, destination, status, row_count
                    FROM analytics_sink_writes
                    WHERE case_id = :case_id AND analysis_run_id = :run_id
                    ORDER BY sink_name, destination
                    """
                ),
                {"case_id": case_id, "run_id": run_id},
            ).mappings().all()
            _assert(len(sink_rows) >= 3, "expected ClickHouse/OpenSearch sink writes")
            by_sink = {str(row["sink_name"]) for row in sink_rows if row["status"] == "succeeded"}
            _assert({"clickhouse", "opensearch"} <= by_sink, "external sink writes did not succeed")
            _assert(
                all(int(row["row_count"] or 0) >= 0 for row in sink_rows),
                "sink write row_count was invalid",
            )
            audit_rows = connection.execute(
                text(
                    """
                    SELECT metadata
                    FROM audit_logs
                    WHERE case_id = :case_id
                      AND target_id = :run_id
                      AND action = 'analytics_query.external'
                    """
                ),
                {"case_id": case_id, "run_id": run_id},
            ).mappings().all()
            reports = {
                str((row["metadata"] or {}).get("report"))
                for row in audit_rows
                if isinstance(row["metadata"], dict)
            }
            _assert({"temporal", "logs"} <= reports, "API did not audit external report queries")
    finally:
        engine.dispose()


def main() -> int:
    api_base_url = _api_base_url()
    s3_endpoint = _default_s3_endpoint(api_base_url)
    upload_public_endpoint = _upload_public_endpoint(api_base_url)
    database_url = _env(
        "LOGAN_FULL_STACK_DATABASE_URL",
        "postgresql+psycopg://logan:logan@localhost:5432/logan",
    )
    clickhouse_url = _env("LOGAN_FULL_STACK_CLICKHOUSE_URL", "http://localhost:8123").rstrip("/")
    clickhouse_database = _safe_clickhouse_identifier(
        _env("LOGAN_FULL_STACK_CLICKHOUSE_DATABASE", _env("LOGAN_CLICKHOUSE_DATABASE", "logan"))
    )
    opensearch_url = _env("LOGAN_FULL_STACK_OPENSEARCH_URL", "http://localhost:9200").rstrip("/")

    with httpx.Client(base_url=api_base_url, timeout=30) as client:
        _log("waiting for API")
        _wait_for_api(client)

        suffix = uuid.uuid4().hex[:10]
        username = f"smoke-{suffix}"
        password = "password123"
        _log("registering smoke user and case")
        _request_json(
            client,
            "POST",
            "/api/auth/register",
            json={
                "email": f"{username}@example.com",
                "username": username,
                "full_name": "Full Stack Smoke",
                "password": password,
            },
        )
        _request_json(
            client,
            "POST",
            "/api/auth/login",
            json={"email_or_username": username, "password": password},
        )
        case = _request_json(
            client,
            "POST",
            "/api/cases",
            json={
                "title": "Full-stack checkout incident smoke",
                "issue_description": "Production checkout intermittently returns 500s.",
                "product": "commerce-platform",
                "service": "checkout",
                "environment": "production",
                "incident_start": "2026-06-06T10:00:00Z",
                "incident_end": "2026-06-06T11:00:00Z",
                "timezone": "UTC",
            },
        )
        case_id = str(case["case_id"])

        _log("uploading logs through MinIO presigned URLs")
        file_ids = _upload_fixtures(
            client,
            case_id=case_id,
            s3_endpoint=s3_endpoint,
            upload_public_endpoint=upload_public_endpoint,
        )
        _assert(len(file_ids) >= 3, "expected at least three uploaded input files")

        _log("starting Temporal-backed analysis")
        started = _request_json(
            client,
            "POST",
            f"/api/cases/{case_id}/analysis-runs",
            json={
                "input_file_ids": file_ids,
                "config": {
                    "default_window_size_seconds": 60,
                    "causal": {
                        "max_lag_seconds": 600,
                        "time_bin_seconds": 60,
                    },
                },
            },
        )
        run_id = str(started["analysis_run_id"])
        run = _wait_for_run(client, case_id, run_id)
        _assert(run.get("progress", {}).get("orchestrator") == "temporal", "run was not temporal")
        _assert_safe_surface("analysis run", run)

        _log("checking reports and job events")
        summary = _request_json(client, "GET", f"/api/cases/{case_id}/analysis-runs/{run_id}/summary")
        temporal = _request_json(client, "GET", f"/api/cases/{case_id}/analysis-runs/{run_id}/temporal")
        logs = _request_json(client, "GET", f"/api/cases/{case_id}/analysis-runs/{run_id}/logs")
        graph = _request_json(client, "GET", f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-graph")
        causal_summary = _request_json(
            client,
            "GET",
            f"/api/cases/{case_id}/analysis-runs/{run_id}/causal-summary",
        )
        reports = {
            "summary": summary,
            "temporal": temporal,
            "logs": logs,
            "causal_graph": graph,
            "causal_summary": causal_summary,
        }
        for name, payload in reports.items():
            _assert_safe_surface(name, payload)
        _assert(summary.get("total", 0) > 0, "summary report was empty")
        _assert(temporal.get("series"), "temporal report was empty")
        _assert(logs.get("total", 0) > 0, "logs report was empty")
        _assert(graph.get("nodes"), "causal graph nodes were empty")
        _assert(causal_summary.get("summary_markdown"), "causal summary was empty")

        events = _request_json(
            client,
            "GET",
            f"/api/cases/{case_id}/analysis-runs/{run_id}/events",
        )
        artifacts = _request_json(
            client,
            "GET",
            f"/api/cases/{case_id}/analysis-runs/{run_id}/artifacts",
        )
        _assert_safe_surface("job events", events)
        _assert_safe_surface("step artifacts", artifacts)
        event_items = events.get("items", [])
        _assert(isinstance(event_items, list), "events payload was invalid")
        completed_steps = {
            str(event.get("step_name"))
            for event in event_items
            if isinstance(event, dict) and event.get("event_type") == "completed"
        }
        _assert("materialize_inputs" in completed_steps, "materialize_inputs event missing")
        _assert(PIPELINE_STEPS <= completed_steps, "not all pipeline steps completed")
        materialize_events = [
            event
            for event in event_items
            if isinstance(event, dict) and event.get("step_name") == "materialize_inputs"
        ]
        _assert(materialize_events, "materialize_inputs event was not recorded")
        storage_counts = materialize_events[0].get("metadata", {}).get("storage_backend_counts")
        _assert(storage_counts == {"s3": len(file_ids)}, "S3 materialization counts were wrong")
        _assert(int(artifacts.get("total", 0)) >= len(PIPELINE_STEPS), "step artifacts missing")

        _log("checking ClickHouse and OpenSearch rows")
        clickhouse_logs = _clickhouse_count(
            clickhouse_url,
            (
                "SELECT count() AS count "
                f"FROM {clickhouse_database}.enriched_log_lines "
                "WHERE case_id = {case_id:String} "
                "AND analysis_run_id = {run_id:String} "
                "FORMAT JSON"
            ),
            case_id=case_id,
            run_id=run_id,
        )
        clickhouse_windows = _clickhouse_count(
            clickhouse_url,
            (
                "SELECT count() AS count "
                f"FROM {clickhouse_database}.window_aggregates "
                "WHERE case_id = {case_id:String} "
                "AND analysis_run_id = {run_id:String} "
                "FORMAT JSON"
            ),
            case_id=case_id,
            run_id=run_id,
        )
        opensearch_docs = _opensearch_count(opensearch_url, case_id=case_id, run_id=run_id)
        _assert(clickhouse_logs > 0, "ClickHouse enriched_log_lines had no rows")
        _assert(clickhouse_windows > 0, "ClickHouse window_aggregates had no rows")
        _assert(opensearch_docs > 0, "OpenSearch had no documents")

        _log("checking SQL sink writes and external-query audits")
        _database_checks(database_url, case_id=case_id, run_id=run_id)

        _log(
            "completed "
            f"run={run_id} files={len(file_ids)} "
            f"clickhouse_logs={clickhouse_logs} "
            f"clickhouse_windows={clickhouse_windows} "
            f"opensearch_docs={opensearch_docs}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - command-line smoke should sanitize failures.
        print(f"[full-stack-smoke] FAILED: {_redact_error(exc)}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
