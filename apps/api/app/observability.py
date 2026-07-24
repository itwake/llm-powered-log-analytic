from __future__ import annotations

import logging
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

_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

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
_MODEL_GATEWAY_REQUESTS_TOTAL = Counter(
    "logan_model_gateway_requests_total",
    "Model gateway requests by provider, model, stream mode, and status.",
    ("provider", "model", "stream", "status"),
)
_MODEL_GATEWAY_REQUEST_DURATION_SECONDS = Histogram(
    "logan_model_gateway_request_duration_seconds",
    "Model gateway request duration in seconds.",
    ("provider", "model", "stream", "status"),
)


def configure_logging(app_settings: Settings) -> int:
    level_name = (app_settings.log_level or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    logging.getLogger("logan").setLevel(level)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=level, format=_LOG_FORMAT)
    return level


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


def record_model_gateway_request(
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
    _MODEL_GATEWAY_REQUESTS_TOTAL.labels(**labels).inc()
    _MODEL_GATEWAY_REQUEST_DURATION_SECONDS.labels(**labels).observe(max(0.0, duration_seconds))


def metrics_text() -> str:
    return generate_latest().decode("utf-8")


def _route_template_for_scope(app: FastAPI, scope: dict[str, Any]) -> str:
    path = _matched_route_path(getattr(app, "routes", []), scope)
    if path is None:
        return "unmatched"
    return _safe_route_label(path)


def _matched_route_path(routes: Any, scope: dict[str, Any]) -> str | None:
    for route in routes or []:
        try:
            match, _ = route.matches(scope)
        except Exception:
            continue
        if match != Match.FULL:
            continue
        path = getattr(route, "path", None)
        if isinstance(path, str) and path:
            return path
        # Newer FastAPI keeps included routers as wrapper objects without a
        # path template; descend into their concrete routes.
        nested = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        return _matched_route_path(nested, scope)
    return None


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
