from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from logan_workers.models import NormalizedLogLine, WindowAggregate


def choose_default_window_size(start: datetime | None, end: datetime | None) -> int:
    if not start or not end:
        return 60
    duration = end - start
    if duration <= timedelta(minutes=30):
        return 10
    if duration <= timedelta(hours=3):
        return 60
    if duration <= timedelta(hours=24):
        return 300
    return 900


def _floor_window(timestamp: datetime, window_size_seconds: int) -> datetime:
    timestamp = timestamp.astimezone(UTC)
    epoch = int(timestamp.timestamp())
    floored = epoch - (epoch % window_size_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)


def build_time_window_aggregates(
    logs: list[NormalizedLogLine], *, window_size_seconds: int | None = None
) -> list[WindowAggregate]:
    timestamps = [line.timestamp for line in logs if line.timestamp]
    size = window_size_seconds or choose_default_window_size(
        min(timestamps) if timestamps else None,
        max(timestamps) if timestamps else None,
    )
    buckets: dict[tuple, int] = defaultdict(int)
    for line in logs:
        if not line.timestamp:
            continue
        window_start = _floor_window(line.timestamp, size)
        categories = line.fault_categories or [None]
        for category in categories:
            key = (
                window_start,
                window_start + timedelta(seconds=size),
                line.template_id,
                line.service,
                line.golden_signal,
                category,
            )
            buckets[key] += 1
    aggregates = [
        WindowAggregate(
            window_start=key[0],
            window_end=key[1],
            window_size_seconds=size,
            template_id=key[2],
            service=key[3],
            golden_signal=key[4],
            fault_category=key[5],
            count=count,
        )
        for key, count in buckets.items()
    ]
    return sorted(aggregates, key=lambda item: (item.window_start, item.golden_signal, item.service or ""))
