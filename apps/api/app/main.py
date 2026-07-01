from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, capabilities, cases, chat, scim
from app.config import validate_runtime_settings
from app.observability import configure_logging, configure_otel, install_metrics
from app.rate_limit import RateLimitMiddleware
from app.services.aiplatform_model_gateway import AIPlatformModelGateway
from app.store import MetadataStore, create_store


def _default_model_gateway(store: MetadataStore) -> object:
    provider = (store.settings.llm_provider or "ai_platform").lower()
    if provider in {"mock", "local_mock"}:
        from logan_workers.activities.inference import MockAIPlatformAnnotationGateway

        return MockAIPlatformAnnotationGateway()
    if provider in {"ai_platform", "ai-platform", "aiplatform", "ai platform"}:
        return AIPlatformModelGateway(app_settings=store.settings)
    raise ValueError("LOGAN_LLM_PROVIDER must be ai_platform or mock")


def create_app(
    store: MetadataStore | None = None,
    *,
    model_gateway: object | None = None,
    s3_client_factory: object | None = None,
    **_legacy_options: object,
) -> FastAPI:
    app = FastAPI(title="LogAn Platform API", version="0.1.0")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.state.store = store or create_store()
    validate_runtime_settings(app.state.store.settings)
    configure_logging(app.state.store.settings)
    app.state.s3_client_factory = s3_client_factory
    app.state.model_gateway = model_gateway or _default_model_gateway(app.state.store)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.store.settings.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware, app_settings=app.state.store.settings)
    app.include_router(auth.router)
    app.include_router(capabilities.router)
    app.include_router(cases.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    app.include_router(scim.router)
    configure_otel(app, app.state.store.settings)
    install_metrics(app, app.state.store.settings)
    return app


app = create_app()
