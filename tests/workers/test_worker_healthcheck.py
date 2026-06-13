from __future__ import annotations

import pytest

from logan_workers import healthcheck
from logan_workers.temporal_client import TemporalUnavailableError


@pytest.mark.asyncio
async def test_check_temporal_connects_with_configured_namespace(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    async def fake_connect(address: str, *, namespace: str) -> object:
        calls.append({"address": address, "namespace": namespace})
        return object()

    monkeypatch.setattr(healthcheck, "_connect_temporal", fake_connect)

    await healthcheck.check_temporal(
        address="temporal:7233",
        namespace="logan",
        timeout_seconds=1,
    )

    assert calls == [{"address": "temporal:7233", "namespace": "logan"}]


@pytest.mark.asyncio
async def test_check_temporal_wraps_connectivity_failures(monkeypatch) -> None:
    async def fake_connect(address: str, *, namespace: str) -> object:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(healthcheck, "_connect_temporal", fake_connect)

    with pytest.raises(TemporalUnavailableError, match="Unable to connect to Temporal"):
        await healthcheck.check_temporal(
            address="temporal:7233",
            namespace="default",
            timeout_seconds=1,
        )


def test_healthcheck_main_returns_zero_for_healthy_dependencies(monkeypatch, capsys) -> None:
    async def fake_check_worker_dependencies(*, timeout_seconds: float) -> None:
        assert timeout_seconds == 2

    monkeypatch.setattr(
        healthcheck,
        "check_worker_dependencies",
        fake_check_worker_dependencies,
    )

    assert healthcheck.main(["--timeout", "2"]) == 0
    assert "worker health check ok" in capsys.readouterr().out


def test_healthcheck_main_returns_nonzero_for_unhealthy_dependencies(monkeypatch, capsys) -> None:
    async def fake_check_worker_dependencies(*, timeout_seconds: float) -> None:
        raise TemporalUnavailableError("temporal unavailable")

    monkeypatch.setattr(
        healthcheck,
        "check_worker_dependencies",
        fake_check_worker_dependencies,
    )

    assert healthcheck.main(["--timeout", "2"]) == 1
    assert "temporal unavailable" in capsys.readouterr().err
