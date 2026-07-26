from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from logan_analysis.ports import ModelGateway

from app.api import auth, cases, chat, reports
from app.config import validate_runtime_settings
from app.logging_config import configure_logging
from app.services.model_gateway_factory import create_model_gateway
from app.store import Store, create_store


def create_app(
    store: Store | None = None,
    *,
    model_gateway: ModelGateway | None = None,
) -> FastAPI:
    app = FastAPI(title="LogAn Platform API", version="0.1.0")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.state.store = store or create_store()
    validate_runtime_settings(app.state.store.settings)
    configure_logging(app.state.store.settings)
    app.state.model_gateway = model_gateway or create_model_gateway(app.state.store.settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.store.settings.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(cases.router)
    app.include_router(reports.router)
    app.include_router(chat.router)
    return app


app = create_app()
