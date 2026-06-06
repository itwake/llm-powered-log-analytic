from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, capabilities, cases, chat, copilot_auth
from app.store import MetadataStore, create_store


def create_app(store: MetadataStore | None = None) -> FastAPI:
    app = FastAPI(title="LogAn Platform API", version="0.1.0")
    app.state.store = store or create_store()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(copilot_auth.router)
    app.include_router(capabilities.router)
    app.include_router(cases.router)
    app.include_router(chat.router)
    return app


app = create_app()
