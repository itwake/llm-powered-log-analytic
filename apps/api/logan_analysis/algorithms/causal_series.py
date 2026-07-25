from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping


@dataclass(frozen=True)
class CountSeries:
    series_by_template: dict[str, list[int]]
    origin: datetime | None
    bin_count: int
    time_bin_seconds: int


def clamp_score(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, value))


def derive_granger_max_lag_bins(
    *,
    max_lag_seconds: int,
    time_bin_seconds: int,
    cap: int = 10,
) -> int:
    if time_bin_seconds <= 0:
        time_bin_seconds = 60
    if max_lag_seconds <= 0:
        return 1
    return max(1, min(cap, math.ceil(max_lag_seconds / time_bin_seconds)))


def build_count_series(
    times_by_template: Mapping[str, Iterable[datetime]],
    *,
    template_ids: Iterable[str] | None = None,
    time_bin_seconds: int = 60,
    origin: datetime | None = None,
    end: datetime | None = None,
) -> CountSeries:
    if time_bin_seconds <= 0:
        raise ValueError("time_bin_seconds must be positive")

    ids = list(template_ids) if template_ids is not None else sorted(times_by_template)
    sorted_times_by_template = {
        template_id: sorted(times_by_template.get(template_id, [])) for template_id in ids
    }
    all_times = [
        timestamp for timestamps in sorted_times_by_template.values() for timestamp in timestamps
    ]
    if not all_times:
        return CountSeries(
            series_by_template={template_id: [] for template_id in ids},
            origin=origin,
            bin_count=0,
            time_bin_seconds=time_bin_seconds,
        )

    origin = origin or min(all_times)
    end = end or max(all_times)
    if end < origin:
        raise ValueError("end must be greater than or equal to origin")

    span_seconds = max(0.0, (end - origin).total_seconds())
    bin_count = max(1, int(span_seconds // time_bin_seconds) + 1)
    series_by_template = {template_id: [0] * bin_count for template_id in ids}

    for template_id, timestamps in sorted_times_by_template.items():
        counts = series_by_template[template_id]
        for timestamp in timestamps:
            offset_seconds = (timestamp - origin).total_seconds()
            if offset_seconds < 0:
                continue
            index = int(offset_seconds // time_bin_seconds)
            if 0 <= index < bin_count:
                counts[index] += 1

    return CountSeries(
        series_by_template=series_by_template,
        origin=origin,
        bin_count=bin_count,
        time_bin_seconds=time_bin_seconds,
    )
