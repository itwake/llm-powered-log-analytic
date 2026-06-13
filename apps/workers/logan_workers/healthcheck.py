from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from logan_workers.temporal_client import TemporalUnavailableError


async def _connect_temporal(address: str, *, namespace: str) -> object:
    try:
        from temporalio.client import Client
    except ImportError as exc:
        raise TemporalUnavailableError(
            "Temporal SDK is not installed. Install temporalio to run worker health checks."
        ) from exc
    return await Client.connect(address, namespace=namespace)


async def check_temporal(
    *,
    address: str,
    namespace: str,
    timeout_seconds: float,
) -> None:
    try:
        await asyncio.wait_for(
            _connect_temporal(address, namespace=namespace),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise TemporalUnavailableError(
            f"Timed out connecting to Temporal at {address} in namespace {namespace}."
        ) from exc
    except TemporalUnavailableError:
        raise
    except Exception as exc:
        raise TemporalUnavailableError(
            f"Unable to connect to Temporal at {address} in namespace {namespace}."
        ) from exc


async def check_worker_dependencies(*, timeout_seconds: float) -> None:
    from app.config import Settings

    app_settings = Settings()
    await check_temporal(
        address=app_settings.temporal_address,
        namespace=app_settings.temporal_namespace,
        timeout_seconds=timeout_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check LogAn worker dependencies.")
    parser.add_argument("--timeout", type=float, default=3.0, help="Temporal connect timeout.")
    args = parser.parse_args(argv)
    try:
        asyncio.run(check_worker_dependencies(timeout_seconds=args.timeout))
    except TemporalUnavailableError as exc:
        print(f"worker health check failed: {exc}", file=sys.stderr)
        return 1
    print("worker health check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
