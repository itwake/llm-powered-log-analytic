from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.services.sso_auth_service import SsoAuthService, SsoUserProfile
from app.store import InMemoryStore


def _unsigned_jwt(payload: dict[str, object]) -> str:
    def encode(value: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode("utf-8")
        ).decode("utf-8").rstrip("=")

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}."


@pytest.mark.asyncio
async def test_sso_exchange_code_reads_standard_claims() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://sso.example.test/token"
        assert parse_qs(request.content.decode("utf-8")) == {
            "grant_type": ["authorization_code"],
            "redirect_uri": ["http://testserver/api/auth/sso/callback"],
            "client_id": ["webapp"],
            "scope": ["offline_access"],
            "code": ["demo-code"],
        }
        return httpx.Response(
            200,
            json={
                "access_token": _unsigned_jwt(
                    {
                        "sub": "sso-user-123",
                        "preferred_username": "logan.engineer",
                        "email": "logan.engineer@example.com",
                        "name": "Logan Engineer",
                    }
                )
            },
        )

    settings = Settings(
        sso_enabled=True,
        sso_token_url="https://sso.example.test/token",
        sso_client_id="webapp",
        sso_token_scope="offline_access",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        service = SsoAuthService(app_settings=settings, http_client=http_client)
        profile = await service.exchange_code(
            redirect_uri="http://testserver/api/auth/sso/callback",
            code="demo-code",
        )

    assert len(requests) == 1
    assert profile == SsoUserProfile(
        username="logan.engineer",
        email="logan.engineer@example.com",
        full_name="Logan Engineer",
        external_id="sso-user-123",
    )


def test_sso_provision_user_rejects_conflicting_matches() -> None:
    settings = Settings(sso_enabled=True)
    store = InMemoryStore(settings)
    store.register_user(
        email="first@example.com",
        username="first-user",
        full_name="First User",
        password="password123",
    )
    store.register_user(
        email="second@example.com",
        username="second-user",
        full_name="Second User",
        password="password123",
    )
    service = SsoAuthService(app_settings=settings)

    with pytest.raises(HTTPException) as caught:
        service.provision_user(
            store,
            SsoUserProfile(
                username="second-user",
                email="first@example.com",
                full_name="Conflicting User",
                external_id="external-1",
            ),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail == "SSO account matches multiple local users"


@pytest.mark.asyncio
async def test_sso_callback_sets_logan_session_and_redirects_to_web() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://sso.example.test/token"
        return httpx.Response(
            200,
            json={
                "access_token": _unsigned_jwt(
                    {
                        "sub": "sso-user-42",
                        "preferred_username": "logan-sso",
                        "email": "logan.sso@example.com",
                        "name": "Logan Sso",
                    }
                )
            },
        )

    settings = Settings(
        cors_allowed_origins="http://localhost:3000",
        sso_enabled=True,
        sso_authorize_url="https://sso.example.test/auth",
        sso_token_url="https://sso.example.test/token",
        sso_client_id="webapp",
    )
    store = InMemoryStore(settings)
    app = create_app(store=store)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as sso_http_client:
        app.state.sso_auth_service = SsoAuthService(
            app_settings=settings,
            http_client=sso_http_client,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            login = await client.get(
                "/api/auth/sso/login",
                params={"next": "/cases/new"},
                follow_redirects=False,
            )
            assert login.status_code == 302
            authorize_location = login.headers["location"]
            parsed_authorize = urlparse(authorize_location)
            authorize_query = parse_qs(parsed_authorize.query)
            assert f"{parsed_authorize.scheme}://{parsed_authorize.netloc}{parsed_authorize.path}" == (
                "https://sso.example.test/auth"
            )
            assert authorize_query["response_type"] == ["code"]
            assert authorize_query["client_id"] == ["webapp"]
            assert authorize_query["redirect_uri"] == ["http://testserver/api/auth/sso/callback"]
            assert client.cookies.get("logan_sso_state")

            callback = await client.get(
                "/api/auth/sso/callback",
                params={
                    "code": "demo-code",
                    "state": authorize_query["state"][0],
                },
                follow_redirects=False,
            )
            assert callback.status_code == 302
            assert callback.headers["location"] == "http://localhost:3000/cases/new"
            assert client.cookies.get("logan_session")

            me = await client.get("/api/auth/me")
            assert me.status_code == 200, me.text
            assert me.json()["user"]["email"] == "logan.sso@example.com"
            assert me.json()["user"]["username"] == "logan-sso"
            assert me.json()["user"]["full_name"] == "Logan Sso"

    stored_user = store.get_user_by_email("logan.sso@example.com")
    assert stored_user is not None
    assert stored_user.external_id == "sso-user-42"


@pytest.mark.asyncio
async def test_sso_profile_derives_readable_name_from_email_when_claim_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": _unsigned_jwt(
                    {
                        "sub": "sso-user-email-name",
                        "preferred_username": "jack.a.b.he",
                        "email": "jack.a.b.he@example.com",
                    }
                )
            },
        )

    settings = Settings(
        sso_enabled=True,
        sso_token_url="https://sso.example.test/token",
        sso_client_id="webapp",
    )
    store = InMemoryStore(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as sso_http_client:
        service = SsoAuthService(app_settings=settings, http_client=sso_http_client)
        profile = await service.exchange_code(
            redirect_uri="http://testserver/api/auth/sso/callback",
            code="demo-code",
        )

    assert profile.full_name == "Jack a b He"


@pytest.mark.asyncio
async def test_mock_sso_provider_can_complete_the_full_login_redirect_flow() -> None:
    settings = Settings(
        cors_allowed_origins="http://localhost:3000",
        web_base_url="http://localhost:3000",
        sso_enabled=True,
        sso_mock_enabled=True,
        sso_authorize_url="http://testserver/api/auth/sso/mock/authorize",
        sso_token_url="http://testserver/api/auth/sso/mock/token",
        sso_client_id="webapp",
        sso_mock_username="playwright-sso",
        sso_mock_email="playwright-sso@example.com",
        sso_mock_full_name="Playwright SSO",
    )
    store = InMemoryStore(settings)
    app = create_app(store=store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as internal_http_client:
        app.state.sso_auth_service = SsoAuthService(
            app_settings=settings,
            http_client=internal_http_client,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            login = await client.get(
                "/api/auth/sso/login",
                params={"next": "/cases"},
                follow_redirects=False,
            )
            assert login.status_code == 302
            assert login.headers["location"].startswith("http://testserver/api/auth/sso/mock/authorize?")

            authorize = await client.get(login.headers["location"], follow_redirects=False)
            assert authorize.status_code == 302
            parsed_callback = urlparse(authorize.headers["location"])
            callback_query = parse_qs(parsed_callback.query)
            assert callback_query["state"]
            assert callback_query["code"]

            callback = await client.get(authorize.headers["location"], follow_redirects=False)
            assert callback.status_code == 302
            assert callback.headers["location"] == "http://localhost:3000/cases"

            me = await client.get("/api/auth/me")
            assert me.status_code == 200, me.text
            assert me.json()["user"]["email"] == "playwright-sso@example.com"
            assert me.json()["user"]["username"] == "playwright-sso"
            assert me.json()["user"]["full_name"] == "Playwright SSO"


