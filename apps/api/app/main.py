from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, capabilities, cases, chat, copilot_auth
from app.observability import configure_otel, install_metrics
from app.rate_limit import RateLimitMiddleware
from app.services.copilot_auth_service import DeviceCodeClient, GitHubDeviceCodeClient
from app.services.copilot_model_gateway import CopilotModelGateway
from app.store import MetadataStore, create_store


def create_app(
    store: MetadataStore | None = None,
    *,
    copilot_auth_client: DeviceCodeClient | None = None,
    model_gateway: object | None = None,
    s3_client_factory: object | None = None,
) -> FastAPI:
    app = FastAPI(title="LogAn Platform API", version="0.1.0")
    app.state.store = store or create_store()
    app.state.s3_client_factory = s3_client_factory
    app.state.copilot_auth_client = copilot_auth_client or GitHubDeviceCodeClient(
        app_settings=app.state.store.settings
    )
    app.state.model_gateway = model_gateway or CopilotModelGateway(
        store=app.state.store,
        app_settings=app.state.store.settings,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware, app_settings=app.state.store.settings)
    app.include_router(auth.router)
    app.include_router(copilot_auth.router)
    app.include_router(capabilities.router)
    app.include_router(cases.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    configure_otel(app, app.state.store.settings)
    install_metrics(app, app.state.store.settings)
    return app


app = create_app()
