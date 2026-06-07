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


@pytest.mark.integration
def test_full_stack_smoke_runner() -> None:
    if os.getenv("LOGAN_RUN_FULL_STACK_SMOKE") != "true":
        pytest.skip("set LOGAN_RUN_FULL_STACK_SMOKE=true to run the full-stack smoke")

    assert main() == 0
