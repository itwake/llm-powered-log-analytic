from __future__ import annotations

import re
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.routing import Match

from app.config import Settings


PIPELINE_STEP_NAMES = frozenset(
    {
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
)

_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")

_HTTP_REQUESTS_TOTAL = Counter(
    "logan_http_requests_total",
    "HTTP requests served by the LogAn API.",
    ("method", "route", "status_code"),
)
_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "logan_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route", "status_code"),
)
_HTTP_REQUESTS_IN_FLIGHT = Gauge(
    "logan_http_requests_in_flight",
    "HTTP requests currently in flight.",
    ("method", "route"),
)
_RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "logan_rate_limit_rejections_total",
    "HTTP requests rejected by the API rate limiter.",
    ("key_type",),
)
_PIPELINE_RUNS_TOTAL = Counter(
    "logan_pipeline_runs_total",
    "Analysis pipeline runs by terminal status.",
    ("status",),
)
_PIPELINE_STEPS_TOTAL = Counter(
    "logan_pipeline_steps_total",
    "Analysis pipeline step events by status.",
    ("step_name", "status"),
)
_PIPELINE_STEP_DURATION_SECONDS = Histogram(
    "logan_pipeline_step_duration_seconds",
    "Analysis pipeline step duration in seconds.",
    ("step_name", "status"),
)
_COPILOT_GATEWAY_REQUESTS_TOTAL = Counter(
    "logan_copilot_gateway_requests_total",
    "Copilot gateway requests by provider, model, stream mode, and status.",
    ("provider", "model", "stream", "status"),
)
_COPILOT_GATEWAY_REQUEST_DURATION_SECONDS = Histogram(
    "logan_copilot_gateway_request_duration_seconds",
    "Copilot gateway request duration in seconds.",
    ("provider", "model", "stream", "status"),
)
_ANALYTICS_SINK_OPERATIONS_TOTAL = Counter(
    "logan_analytics_sink_operations_total",
    "Analytics sink operations by sink and status.",
    ("sink_name", "status"),
)
_ANALYTICS_SINK_OPERATION_DURATION_SECONDS = Histogram(
    "logan_analytics_sink_operation_duration_seconds",
    "Analytics sink operation duration in seconds.",
    ("sink_name", "status"),
)
_ANALYTICS_SINK_ROWS_TOTAL = Counter(
    "logan_analytics_sink_rows_total",
    "Analytics sink rows written by sink and status.",
    ("sink_name", "status"),
)


def install_metrics(app: FastAPI, app_settings: Settings) -> bool:
    if not app_settings.metrics_enabled:
        return False

    metrics_path = app_settings.metrics_path or "/metrics"

    @app.get(metrics_path, include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    @app.middleware("http")
    async def prometheus_http_metrics(request: Request, call_next: Any) -> Response:
        if request.url.path == metrics_path:
            return await call_next(request)

        method = _safe_label(request.method.upper())
        route = _route_template_for_scope(app, request.scope)
        status_code = "500"
        started_at = time.perf_counter()
        _HTTP_REQUESTS_IN_FLIGHT.labels(method=method, route=route).inc()
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            return response
        finally:
            duration = max(0.0, time.perf_counter() - started_at)
            _HTTP_REQUESTS_TOTAL.labels(
                method=method,
                route=route,
                status_code=status_code,
            ).inc()
            _HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method,
                route=route,
                status_code=status_code,
            ).observe(duration)
            _HTTP_REQUESTS_IN_FLIGHT.labels(method=method, route=route).dec()

    return True


def configure_otel(app: FastAPI, app_settings: Settings) -> bool:
    if not app_settings.otel_enabled:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        return False

    resource = Resource.create(
        {"service.name": app_settings.otel_service_name or "logan-api"}
    )
    tracer_provider = TracerProvider(resource=resource)
    endpoint = app_settings.otel_exporter_otlp_endpoint
    if endpoint:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
    try:
        trace.set_tracer_provider(tracer_provider)
    except Exception:
        pass
    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    return True


def record_rate_limit_rejection(key_type: str) -> None:
    if key_type not in {"session", "ip", "unknown"}:
        key_type = "unknown"
    _RATE_LIMIT_REJECTIONS_TOTAL.labels(key_type=key_type).inc()


def record_pipeline_run_started() -> None:
    _PIPELINE_RUNS_TOTAL.labels(status="started").inc()


def record_pipeline_run_completed() -> None:
    _PIPELINE_RUNS_TOTAL.labels(status="completed").inc()


def record_pipeline_run_failed() -> None:
    _PIPELINE_RUNS_TOTAL.labels(status="failed").inc()


def record_pipeline_step_started(step_name: str) -> None:
    _PIPELINE_STEPS_TOTAL.labels(
        step_name=_pipeline_step_label(step_name),
        status="started",
    ).inc()


def record_pipeline_step_completed(step_name: str, duration_seconds: float) -> None:
    step_label = _pipeline_step_label(step_name)
    _PIPELINE_STEPS_TOTAL.labels(step_name=step_label, status="completed").inc()
    _PIPELINE_STEP_DURATION_SECONDS.labels(
        step_name=step_label,
        status="completed",
    ).observe(max(0.0, duration_seconds))


def record_pipeline_step_failed(step_name: str, duration_seconds: float) -> None:
    step_label = _pipeline_step_label(step_name)
    _PIPELINE_STEPS_TOTAL.labels(step_name=step_label, status="failed").inc()
    _PIPELINE_STEP_DURATION_SECONDS.labels(
        step_name=step_label,
        status="failed",
    ).observe(max(0.0, duration_seconds))


def record_copilot_gateway_request(
    *,
    provider: str,
    model: str,
    stream: bool,
    status: str,
    duration_seconds: float,
) -> None:
    labels = {
        "provider": _safe_label(provider),
        "model": _safe_label(model),
        "stream": "true" if stream else "false",
        "status": _status_label(status),
    }
    _COPILOT_GATEWAY_REQUESTS_TOTAL.labels(**labels).inc()
    _COPILOT_GATEWAY_REQUEST_DURATION_SECONDS.labels(**labels).observe(
        max(0.0, duration_seconds)
    )


def record_analytics_sink_operation(
    *,
    sink_name: str,
    status: str,
    duration_seconds: float,
    row_count: int,
) -> None:
    labels = {
        "sink_name": _safe_label(sink_name),
        "status": _status_label(status),
    }
    _ANALYTICS_SINK_OPERATIONS_TOTAL.labels(**labels).inc()
    _ANALYTICS_SINK_OPERATION_DURATION_SECONDS.labels(**labels).observe(
        max(0.0, duration_seconds)
    )
    if row_count > 0:
        _ANALYTICS_SINK_ROWS_TOTAL.labels(**labels).inc(row_count)


def metrics_text() -> str:
    return generate_latest().decode("utf-8")


def _route_template_for_scope(app: FastAPI, scope: dict[str, Any]) -> str:
    for route in app.routes:
        try:
            match, _ = route.matches(scope)
        except Exception:
            continue
        if match == Match.FULL:
            return _safe_route_label(getattr(route, "path", "unknown"))
    return "unmatched"


def _pipeline_step_label(step_name: str) -> str:
    return step_name if step_name in PIPELINE_STEP_NAMES else "unknown"


def _safe_route_label(route: str) -> str:
    if not route or any(part in route.lower() for part in ("token", "secret", "password")):
        return "unknown"
    return route if len(route) <= 160 else "unknown"


def _safe_label(value: object) -> str:
    text = str(value or "unknown")
    return text if _SAFE_LABEL_RE.fullmatch(text) else "unknown"


def _status_label(status: str) -> str:
    allowed_statuses = {"started", "completed", "succeeded", "failed", "skipped"}
    return status if status in allowed_statuses else "failed"
