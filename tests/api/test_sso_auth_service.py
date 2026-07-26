from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.config import Settings
from app.main import create_app
from app.services.sso_auth_service import SsoAuthService
from app.store import create_ephemeral_store
from httpx import ASGITransport, AsyncClient


def _jwt(payload: dict[str, object]) -> str:
    def encode(value: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).decode().rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode(payload)}."


@pytest.mark.asyncio
async def test_sso_callback_provisions_user_and_session() -> None:
    def token_response(request: httpx.Request) -> httpx.Response:
        assert parse_qs(request.content.decode())["code"] == ["demo-code"]
        return httpx.Response(
            200,
            json={
                "access_token": _jwt(
                    {
                        "sub": "subject-1",
                        "preferred_username": "logan.engineer",
                        "email": "engineer@example.com",
                        "name": "Logan Engineer",
                    }
                )
            },
        )

    settings = Settings(
        web_base_url="http://localhost:3000",
        sso_authorize_url="https://sso.example.test/authorize",
        sso_token_url="https://sso.example.test/token",
        sso_client_id="logan",
    )
    store = create_ephemeral_store(settings)
    app = create_app(store=store)
    async with httpx.AsyncClient(transport=httpx.MockTransport(token_response)) as sso_client:
        app.state.sso_auth_service = SsoAuthService(
            app_settings=settings,
            http_client=sso_client,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            login = await client.get(
                "/api/auth/sso/login",
                params={"next": "/cases"},
                follow_redirects=False,
            )
            assert login.status_code == 302
            authorize = urlparse(login.headers["location"])
            query = parse_qs(authorize.query)
            assert query["client_id"] == ["logan"]

            callback = await client.get(
                "/api/auth/sso/callback",
                params={"code": "demo-code", "state": query["state"][0]},
                follow_redirects=False,
            )
            assert callback.status_code == 302
            assert callback.headers["location"] == "http://localhost:3000/cases"
            assert client.cookies.get("logan_session")

            me = await client.get("/api/auth/me")
            assert me.json()["user"] == {
                "id": store.get_user_by_external_id("subject-1").id,
                "email": "engineer@example.com",
                "username": "logan.engineer",
                "full_name": "Logan Engineer",
            }


def test_sso_requires_complete_configuration() -> None:
    with pytest.raises(ValueError, match="SSO URLs and client id"):
        Settings(env="production", secret_key="x" * 32).validate_for_runtime()
