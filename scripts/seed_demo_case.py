#!/usr/bin/env python3
"""Seed a ready-made demo case against a running LogAn API.

Signs in through the local mock SSO, creates a case, uploads the bundled
checkout-incident sample logs, runs a synchronous analysis, and prints the
workbench URLs to open. Requires the API from the README Quick Start
(mock SSO enabled, local object store) and, for clicking through the result,
the web workbench.

Usage:
    python scripts/seed_demo_case.py
    python scripts/seed_demo_case.py --api-base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "logs" / "checkout_incident"
FIXTURE_NAMES = ("auth.log", "payment.log", "gateway.log")
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _log(message: str) -> None:
    print(f"[demo] {message}", flush=True)


def _fail(message: str) -> int:
    print(f"[demo] ERROR: {message}", file=sys.stderr, flush=True)
    return 1


def _login_via_mock_sso(client: httpx.Client, api_base_url: str) -> str | None:
    """Walk the SSO redirect chain manually; returns an error message or None."""
    api = httpx.URL(api_base_url)
    response = client.get("/api/auth/sso/login", params={"next": "/cases"})
    if response.status_code == 503:
        return (
            "SSO is disabled on the API. Local runs need LOGAN_SSO_ENABLED=true and "
            "LOGAN_SSO_MOCK_ENABLED=true; copy .env.example to .env and start the API "
            "with it loaded (scripts\\dev.ps1 does this)."
        )
    hops = 0
    while response.status_code in REDIRECT_STATUSES:
        location = response.headers.get("location", "")
        if not location:
            return "SSO redirect response is missing a Location header."
        target = httpx.URL(location)
        if not target.path.startswith("/api/"):
            break  # post-login redirect to the web workbench ends the chain
        if target.host and target.host != api.host:
            target = target.copy_with(scheme=api.scheme, host=api.host, port=api.port)
        hops += 1
        if hops > 5:
            return "SSO login redirect chain is too long."
        response = client.get(str(target))
    me = client.get("/api/auth/me")
    if me.status_code != 200:
        return f"sign-in did not establish a session (/api/auth/me -> {me.status_code})."
    user = me.json().get("user", {})
    _log(f"signed in as {user.get('email', 'unknown user')}")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("LOGAN_DEMO_API_BASE_URL", "http://localhost:8000"),
        help="API origin (default: %(default)s)",
    )
    parser.add_argument(
        "--web-base-url",
        default=os.getenv("LOGAN_DEMO_WEB_BASE_URL", "http://localhost:3000"),
        help="Workbench origin used for the printed links (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    api_base_url = args.api_base_url.rstrip("/")
    web_base_url = args.web_base_url.rstrip("/")

    missing = [name for name in FIXTURE_NAMES if not (FIXTURE_DIR / name).is_file()]
    if missing:
        return _fail(f"sample logs not found under {FIXTURE_DIR}: {', '.join(missing)}")

    with httpx.Client(base_url=api_base_url, timeout=300) as client:
        try:
            health = client.get("/healthz")
        except httpx.HTTPError as exc:
            return _fail(
                f"cannot reach the API at {api_base_url} ({exc.__class__.__name__}). "
                "Start it first: scripts\\dev.ps1 -ApiOnly, or see the README Quick Start."
            )
        if health.status_code != 200:
            return _fail(f"API health check returned HTTP {health.status_code}.")

        error = _login_via_mock_sso(client, api_base_url)
        if error:
            return _fail(error)

        case = client.post(
            "/api/cases",
            json={
                "title": "Demo: checkout incident walkthrough",
                "issue_description": "Customers report intermittent 500s during checkout.",
                "product": "commerce-platform",
                "service": "checkout",
                "environment": "production",
                "incident_start": "2026-06-06T10:00:00Z",
                "incident_end": "2026-06-06T11:00:00Z",
                "timezone": "UTC",
            },
        )
        if case.status_code != 200:
            return _fail(f"case creation failed: HTTP {case.status_code} {case.text[:200]}")
        case_id = case.json()["case_id"]
        _log(f"created case {case_id}")

        file_ids: list[str] = []
        for name in FIXTURE_NAMES:
            content = (FIXTURE_DIR / name).read_bytes()
            upload = client.post(
                f"/api/cases/{case_id}/uploads",
                json={
                    "filename": name,
                    "content_type": "text/plain",
                    "size_bytes": len(content),
                },
            )
            if upload.status_code != 200:
                return _fail(f"upload request for {name} failed: HTTP {upload.status_code}")
            info = upload.json()
            if info.get("upload_backend") != "local":
                return _fail(
                    "this demo only supports the local object store "
                    f"(got backend {info.get('upload_backend')!r}); for S3/MinIO use "
                    "scripts/full_stack_smoke.py instead."
                )
            put = client.put(
                info["upload_url"],
                content=content,
                headers={"Content-Type": "text/plain"},
            )
            if put.status_code != 200:
                return _fail(f"upload of {name} failed: HTTP {put.status_code}")
            file_ids.append(info["file_id"])
        _log(f"uploaded {len(file_ids)} sample log files")

        _log("running analysis (synchronous; takes a few seconds)")
        run = client.post(
            f"/api/cases/{case_id}/analysis-runs",
            json={"input_file_ids": file_ids},
        )
        if run.status_code != 200:
            return _fail(f"analysis failed to start: HTTP {run.status_code} {run.text[:200]}")
        run_id = run.json()["analysis_run_id"]
        status = run.json().get("status")
        if status != "completed":
            return _fail(f"analysis run {run_id} ended with status {status!r}.")
        _log(f"analysis run {run_id} completed")

    base = f"{web_base_url}/cases/{case_id}/runs/{run_id}"
    print()
    print("Demo case is ready. Open the workbench views:")
    for view in ("summary", "temporal", "logs", "causal-graph", "causal-summary"):
        print(f"  {base}/{view}")
    print()
    print("Sign in with 'Continue with SSO' if prompted (local mock, no credentials).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
