from __future__ import annotations

import os

import httpx
import pytest

from scripts import full_stack_smoke as smoke
from scripts.full_stack_smoke import main


def test_clickhouse_count_uses_env_basic_auth_and_redacts_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGAN_CLICKHOUSE_USERNAME", "logan")
    monkeypatch.setenv("LOGAN_CLICKHOUSE_PASSWORD", "fallback-secret")
    monkeypatch.setenv("LOGAN_FULL_STACK_CLICKHOUSE_USERNAME", "smoke")
    monkeypatch.setenv("LOGAN_FULL_STACK_CLICKHOUSE_PASSWORD", "smoke-secret")

    username, password = smoke._clickhouse_credentials()
    assert (username, password) == ("smoke", "smoke-secret")
    assert "smoke-secret" not in smoke._redact_error("failed with smoke-secret")

    monkeypatch.delenv("LOGAN_FULL_STACK_CLICKHOUSE_USERNAME")
    monkeypatch.delenv("LOGAN_FULL_STACK_CLICKHOUSE_PASSWORD")
    assert smoke._clickhouse_credentials() == ("logan", "fallback-secret")

    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["auth"] = kwargs.get("auth")
        captured["params"] = kwargs.get("params")
        return httpx.Response(
            200,
            json={"data": [{"count": 7}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(smoke.httpx, "post", fake_post)

    count = smoke._clickhouse_count(
        "http://clickhouse:8123",
        "SELECT count() AS count FORMAT JSON",
        case_id="case-1",
        run_id="run-1",
        username=username,
        password=password,
    )

    assert count == 7
    assert captured["url"] == "http://clickhouse:8123"
    assert isinstance(captured["auth"], httpx.BasicAuth)
    assert "smoke-secret" not in str(captured["url"])
    assert "fallback-secret" not in smoke._redact_error("failed with fallback-secret")


def test_login_via_sso_rewrites_local_authorize_url_to_api_origin() -> None:
    class FakeSsoClient:
        def __init__(self) -> None:
            self.base_url = httpx.URL("http://api:8000")
            self.cookies = httpx.Cookies()
            self.calls: list[str] = []

        def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            assert method == "GET"
            return self.get(
                url,
                params=kwargs.get("params"),
                follow_redirects=bool(kwargs.get("follow_redirects", False)),
            )

        def get(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
            follow_redirects: bool = False,
        ) -> httpx.Response:
            request_url = url if url.startswith("http") else f"http://api:8000{url}"
            request = httpx.Request("GET", request_url, params=params)
            self.calls.append(str(request.url))

            if url == "/api/auth/sso/login":
                return httpx.Response(
                    302,
                    headers={
                        "location": "http://localhost:8000/api/auth/sso/mock/authorize"
                        "?redirect_uri=http://api:8000/api/auth/sso/callback"
                    },
                    request=request,
                )
            if url.startswith("http://api:8000/api/auth/sso/mock/authorize"):
                return httpx.Response(
                    302,
                    headers={"location": "http://api:8000/api/auth/sso/callback?code=mock"},
                    request=request,
                )
            if url.startswith("http://api:8000/api/auth/sso/callback"):
                self.cookies.set("logan_session", "session-token")
                return httpx.Response(
                    302,
                    headers={"location": "http://localhost:3000/cases"},
                    request=request,
                )
            if url == "/api/auth/me":
                return httpx.Response(200, json={"user": {"id": "user-1"}}, request=request)
            raise AssertionError(f"unexpected SSO request: {url}")

    client = FakeSsoClient()
    smoke._login_via_sso(client, api_base_url="http://api:8000")

    assert client.calls[0] == "http://api:8000/api/auth/sso/login?next=%2Fcases"
    assert client.calls[1].startswith("http://api:8000/api/auth/sso/mock/authorize?")
    assert client.calls[2].startswith("http://api:8000/api/auth/sso/callback?code=mock")
    assert client.calls[3] == "http://api:8000/api/auth/me"
    assert client.cookies.get("logan_session") == "session-token"


@pytest.mark.integration
def test_full_stack_smoke_runner() -> None:
    if os.getenv("LOGAN_RUN_FULL_STACK_SMOKE") != "true":
        pytest.skip("set LOGAN_RUN_FULL_STACK_SMOKE=true to run the full-stack smoke")

    assert main() == 0
