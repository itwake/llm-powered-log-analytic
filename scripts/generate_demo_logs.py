#!/usr/bin/env python3
"""Generate the deterministic demo incident log set under demo/logs/.

The scenario is a one-hour window (10:00-11:00 UTC) around a checkout outage:
auth-service's database connection pool saturates at 10:10, payment-service
starts timing out calling auth-service at 10:11, and the gateway returns 500s
on POST /checkout from 10:12 until recovery at about 10:33. Healthy traffic
runs before and after, so the Temporal View shows a clear incident wave.

The line wording is deliberately aligned with the deterministic mock
annotation gateway's keyword rules (connection pool exhausted -> saturation,
timeout calling <service> -> availability, failed status=500 -> error, disk
error -> infrastructure error), so the demo works fully offline with
LOGAN_LLM_PROVIDER=mock. The set also includes multi-line Java stack traces
(multi-line merge), lines with emails/IPs/tokens/card numbers (redaction),
and a gzip-compressed batch log (archive ingestion).

Usage:
    python scripts/generate_demo_logs.py [--out-dir demo/logs]
"""
from __future__ import annotations

import argparse
import gzip
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = datetime(2026, 6, 6, 10, 0, 0, tzinfo=UTC)
INCIDENT_AUTH_START = BASE + timedelta(minutes=10)
INCIDENT_PAYMENT_START = BASE + timedelta(minutes=11)
INCIDENT_GATEWAY_START = BASE + timedelta(minutes=12)
INCIDENT_END = BASE + timedelta(minutes=33)
WINDOW_END = BASE + timedelta(minutes=60)

STACK_TRACE = [
    "    at com.logan.payment.AuthClient.call(AuthClient.java:87)",
    "    at com.logan.payment.PaymentProcessor.authorize(PaymentProcessor.java:142)",
    "    at com.logan.payment.api.ChargeController.charge(ChargeController.java:58)",
    "    Caused by: java.net.SocketTimeoutException: connect timed out",
    "    at java.base/java.net.Socket.connect(Socket.java:751)",
    "    at com.logan.payment.AuthClient.open(AuthClient.java:41)",
]

FIRST_NAMES = ("alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi")


def _ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _in_incident(moment: datetime, start: datetime) -> bool:
    return start <= moment < INCIDENT_END


def _walk(rng: random.Random, start: datetime, end: datetime, base_step: float, jitter: float):
    moment = start
    while moment < end:
        yield moment
        moment += timedelta(seconds=base_step + rng.uniform(-jitter, jitter))


def build_auth_log(rng: random.Random) -> list[tuple[datetime, str]]:
    lines: list[tuple[datetime, str]] = []
    for moment in _walk(rng, BASE, WINDOW_END, 8, 3):
        if _in_incident(moment, INCIDENT_AUTH_START):
            continue
        user = rng.randint(1, 900)
        lines.append(
            (moment, f"INFO auth-service session validated user_id=u-{user:04d} "
                     f"duration_ms={rng.randint(4, 28)}")
        )
    for moment in _walk(rng, BASE, WINDOW_END, 20, 4):
        active = 50 if _in_incident(moment, INCIDENT_AUTH_START) else rng.randint(6, 24)
        lines.append(
            (moment, f"INFO auth-service healthcheck ok pool_active={active} pool_max=50")
        )
    # Ramp: pool usage climbs in the two minutes before exhaustion.
    for moment in _walk(rng, INCIDENT_AUTH_START - timedelta(minutes=2), INCIDENT_AUTH_START, 9, 2):
        lines.append(
            (moment, f"WARN auth-service db connection pool usage high "
                     f"active={rng.randint(44, 49)} max=50")
        )
    # Incident: exhaustion plus acquisition failures.
    for moment in _walk(rng, INCIDENT_AUTH_START, INCIDENT_END, 13, 4):
        lines.append(
            (moment, f"ERROR auth-service db connection pool exhausted active=50 max=50 "
                     f"waiters={rng.randint(4, 31)}")
        )
    for moment in _walk(rng, INCIDENT_AUTH_START + timedelta(seconds=30), INCIDENT_END, 15, 5):
        lines.append(
            (moment, f"ERROR auth-service failed to acquire db connection timeout_ms=5000 "
                     f"request_id=req-{rng.randint(1000, 9999)}")
        )
    lines.append(
        (INCIDENT_END + timedelta(seconds=5),
         "INFO auth-service db connection pool recovered active=11 max=50")
    )
    return lines


def build_payment_log(rng: random.Random) -> list[tuple[datetime, str]]:
    lines: list[tuple[datetime, str]] = []
    for moment in _walk(rng, BASE, WINDOW_END, 10, 4):
        if _in_incident(moment, INCIDENT_PAYMENT_START) and rng.random() < 0.85:
            continue  # most authorizations fail during the outage
        order = rng.randint(2000, 9800)
        lines.append(
            (moment, f"INFO payment-service payment authorized order_id=ord-{order} "
                     f"amount_cents={rng.randint(900, 250000)} currency=USD")
        )
    for moment in _walk(rng, INCIDENT_PAYMENT_START, INCIDENT_END, 12, 4):
        lines.append(
            (moment, f"ERROR payment-service timeout calling auth-service after 30000ms "
                     f"request_id=req-{rng.randint(1000, 9999)}")
        )
    for moment in _walk(rng, INCIDENT_PAYMENT_START, INCIDENT_END, 30, 8):
        lines.append(
            (moment, f"WARN payment-service retry scheduled for auth-service "
                     f"attempt={rng.randint(1, 3)} request_id=req-{rng.randint(1000, 9999)}")
        )
    # Three merged multi-line stack traces from the same failure template.
    for offset_minutes in (12.7, 18.2, 27.5):
        moment = BASE + timedelta(minutes=offset_minutes)
        order = rng.randint(2000, 9800)
        lines.append(
            (moment, f"ERROR payment-service payment processing failed order_id=ord-{order} "
                     f"unhandled exception")
        )
        for index, frame in enumerate(STACK_TRACE):
            lines.append((moment + timedelta(milliseconds=index), frame))
    return lines


def build_gateway_log(rng: random.Random) -> list[tuple[datetime, str]]:
    lines: list[tuple[datetime, str]] = []
    request = 1
    for moment in _walk(rng, BASE, WINDOW_END, 6, 2):
        request += 1
        lines.append((moment, f"INFO gateway request_id=req-{request} POST /checkout started"))
        if _in_incident(moment, INCIDENT_GATEWAY_START) and rng.random() < 0.8:
            lines.append(
                (moment + timedelta(seconds=30),
                 f"ERROR gateway request_id=req-{request} POST /checkout failed status=500 "
                 f"duration_ms={rng.randint(30000, 31500)}")
            )
        else:
            lines.append(
                (moment + timedelta(milliseconds=rng.randint(90, 450)),
                 f"INFO gateway request_id=req-{request} POST /checkout completed "
                 f"duration_ms={rng.randint(80, 420)}")
            )
    for moment in _walk(rng, BASE, WINDOW_END, 15, 3):
        lines.append(
            (moment, f"INFO gateway GET /healthz completed duration_ms={rng.randint(1, 6)}")
        )
    # Lines that exist to demonstrate redaction in the Tabular Logs view.
    for index, offset_minutes in enumerate((3.5, 7.2, 16.4, 24.9, 38.6, 45.1, 52.8, 57.3)):
        moment = BASE + timedelta(minutes=offset_minutes)
        name = FIRST_NAMES[index % len(FIRST_NAMES)]
        session = uuid.UUID(int=rng.getrandbits(128))
        lines.append(
            (moment, f"INFO gateway user profile updated user_email={name}.demo@example.com "
                     f"client_ip=203.0.113.{rng.randint(2, 250)} session_id={session}")
        )
        lines.append(
            (moment + timedelta(seconds=2),
             f"INFO gateway payment method saved card_number=4111111111111111 "
             f"api_key=sk_live_demo_{rng.getrandbits(48):012x} "
             f"auth_header=Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vLXVzZXIifQ."
             f"sig{rng.getrandbits(32):08x}")
        )
    return lines


def build_batch_log(rng: random.Random) -> list[tuple[datetime, str]]:
    lines: list[tuple[datetime, str]] = []
    for moment in _walk(rng, BASE, WINDOW_END, 45, 10):
        lines.append(
            (moment, f"INFO batch-runner export shard completed rows={rng.randint(500, 9000)} "
                     f"duration_ms={rng.randint(200, 4000)}")
        )
    for offset_minutes in (14.3, 21.8, 29.1):
        moment = BASE + timedelta(minutes=offset_minutes)
        lines.append(
            (moment, f"ERROR batch-runner disk error writing shard part-{rng.randint(10, 99)} "
                     f"will retry")
        )
    return lines


def _render(lines: list[tuple[datetime, str]]) -> str:
    ordered = sorted(lines, key=lambda item: item[0])
    rendered: list[str] = []
    for moment, text in ordered:
        if text.startswith(" "):
            rendered.append(text)  # stack continuation lines carry no timestamp
        else:
            rendered.append(f"{_ts(moment)} {text}")
    return "\n".join(rendered) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "demo" / "logs"),
        help="Directory for the generated demo logs (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(1106)
    outputs = {
        "auth-service.log": _render(build_auth_log(rng)),
        "payment-service.log": _render(build_payment_log(rng)),
        "gateway.log": _render(build_gateway_log(rng)),
    }
    total = 0
    for name, content in outputs.items():
        (out_dir / name).write_text(content, encoding="utf-8", newline="\n")
        count = content.count("\n")
        total += count
        print(f"wrote {name}: {count} lines")
    batch = _render(build_batch_log(rng))
    with gzip.open(out_dir / "batch-jobs.log.gz", "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(batch)
    total += batch.count("\n")
    print(f"wrote batch-jobs.log.gz: {batch.count(chr(10))} lines (gzip)")
    print(f"total: {total} lines in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
