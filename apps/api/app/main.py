from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from logan_analysis.ports import ModelGateway

from app.api import auth, cases, chat, llm_providers, reports
from app.config import validate_runtime_settings
from app.logging_config import configure_logging
from app.services.github_copilot_auth import GitHubDeviceFlow
from app.services.model_gateway_factory import ModelGatewayRegistry
from app.store import Store, create_store

logger = logging.getLogger("logan.analysis")


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncIterator[None]:
    interrupted = await asyncio.to_thread(app.state.store.fail_interrupted_analysis_runs)
    if interrupted:
        logger.warning(
            "marked interrupted analysis runs as failed",
            extra={"analysis_run_count": interrupted},
        )
    yield
    tasks = list(getattr(app.state, "analysis_tasks", {}).values())
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await app.state.gateway_registry.aclose()
    device_flow = getattr(app.state, "github_device_flow", None)
    if isinstance(device_flow, GitHubDeviceFlow):
        await device_flow.aclose()


def create_app(
    store: Store | None = None,
    *,
    model_gateway: ModelGateway | None = None,
) -> FastAPI:
    """Build the API. ``model_gateway`` lets tests answer every provider with one fake."""
    app = FastAPI(title="LogAn Platform API", version="0.1.0", lifespan=app_lifespan)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.state.store = store or create_store()
    validate_runtime_settings(app.state.store.settings)
    configure_logging(app.state.store.settings)
    app.state.gateway_registry = ModelGatewayRegistry(
        app.state.store.settings,
        override=model_gateway,
    )
    app.state.github_device_flow = GitHubDeviceFlow(app_settings=app.state.store.settings)
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
    app.include_router(llm_providers.router)
    return app


app = create_app()
