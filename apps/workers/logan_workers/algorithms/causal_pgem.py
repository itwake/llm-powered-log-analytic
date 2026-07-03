from __future__ import annotations

import math
import statistics
from bisect import bisect_left, bisect_right
from datetime import datetime
from datetime import timedelta
from typing import Any

from logan_workers.algorithms.causal_series import clamp_score


def _round_optional(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _unsupported(
    reason: str,
    *,
    source_events: int,
    target_events: int,
    support: int = 0,
    target_coverage: float = 0.0,
    lift: float = 0.0,
    median_lag_seconds: float | None = None,
) -> dict[str, Any]:
    return {
        "supported": False,
        "score": 0.0,
        "support": support,
        "source_events": source_events,
        "target_events": target_events,
        "target_coverage": round(target_coverage, 6),
        "lift": round(lift, 6),
        "median_lag_seconds": _round_optional(median_lag_seconds),
        "reason": reason,
    }


def score_pgem_transition(
    source_times: list[datetime],
    target_times: list[datetime],
    *,
    max_lag_seconds: int,
    observation_start: datetime | None = None,
    observation_end: datetime | None = None,
    min_events: int = 2,
    min_support: int = 1,
) -> dict[str, Any]:
    source_times = sorted(source_times)
    target_times = sorted(target_times)
    source_events = len(source_times)
    target_events = len(target_times)

    if max_lag_seconds <= 0:
        return _unsupported(
            "invalid_max_lag",
            source_events=source_events,
            target_events=target_events,
        )
    if source_events < min_events or target_events < min_events:
        return _unsupported(
            "too_few_events",
            source_events=source_events,
            target_events=target_events,
        )

    source_follow_lags: list[float] = []
    for source in source_times:
        window_end = source + timedelta(seconds=max_lag_seconds)
        first_target = bisect_right(target_times, source)
        last_target = bisect_right(target_times, window_end)
        if first_target < last_target:
            source_follow_lags.append(
                (target_times[first_target] - source).total_seconds()
            )

    target_preceded_lags: list[float] = []
    for target in target_times:
        window_start = target - timedelta(seconds=max_lag_seconds)
        first_source = bisect_left(source_times, window_start)
        target_index = bisect_left(source_times, target)
        if first_source < target_index:
            nearest_source = source_times[target_index - 1]
            target_preceded_lags.append((target - nearest_source).total_seconds())

    support = len(source_follow_lags)
    target_coverage = len(target_preceded_lags) / target_events if target_events else 0.0
    source_support_rate = support / source_events if source_events else 0.0
    lags = target_preceded_lags or source_follow_lags
    median_lag_seconds = statistics.median(lags) if lags else None

    all_times = source_times + target_times
    observation_start = observation_start or min(all_times)
    observation_end = observation_end or max(all_times)
    span_seconds = max(max_lag_seconds, (observation_end - observation_start).total_seconds())
    target_rate = target_events / span_seconds if span_seconds > 0 else 0.0
    baseline_probability = 1.0 - math.exp(-target_rate * max_lag_seconds)
    lift = source_support_rate / max(baseline_probability, 1e-9)

    if support < min_support:
        return _unsupported(
            "no_source_target_transition",
            source_events=source_events,
            target_events=target_events,
            support=support,
            target_coverage=target_coverage,
            lift=lift,
            median_lag_seconds=median_lag_seconds,
        )
    if lift < 1.0:
        return _unsupported(
            "transition_not_above_baseline",
            source_events=source_events,
            target_events=target_events,
            support=support,
            target_coverage=target_coverage,
            lift=lift,
            median_lag_seconds=median_lag_seconds,
        )

    lift_score = lift / (1.0 + lift)
    sample_score = min(1.0, support / 3)
    score = clamp_score(
        0.40 * source_support_rate
        + 0.30 * target_coverage
        + 0.20 * lift_score
        + 0.10 * sample_score
    )

    return {
        "supported": True,
        "score": round(score, 6),
        "support": support,
        "source_events": source_events,
        "target_events": target_events,
        "source_support_rate": round(source_support_rate, 6),
        "target_coverage": round(target_coverage, 6),
        "baseline_target_probability": round(baseline_probability, 6),
        "lift": round(lift, 6),
        "median_lag_seconds": _round_optional(median_lag_seconds),
    }
