from __future__ import annotations

from datetime import UTC, datetime, timedelta

from logan_workers.algorithms.causal_granger import (
    benjamini_hochberg,
    score_granger_pair,
    score_granger_pairs,
)
from logan_workers.algorithms.causal_pgem import score_pgem_transition
from logan_workers.algorithms.causal_series import build_count_series


def test_pgem_scores_source_preceding_target_direction_more_strongly() -> None:
    base = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    source_times = [base + timedelta(minutes=index * 4) for index in range(8)]
    target_times = [timestamp + timedelta(seconds=45) for timestamp in source_times]

    forward = score_pgem_transition(
        source_times,
        target_times,
        max_lag_seconds=90,
    )
    reverse = score_pgem_transition(
        target_times,
        source_times,
        max_lag_seconds=90,
    )

    assert forward["supported"] is True
    assert forward["support"] == len(source_times)
    assert forward["target_coverage"] == 1.0
    assert forward["median_lag_seconds"] == 45
    assert reverse["supported"] is False
    assert forward["score"] > reverse["score"]


def test_granger_scores_source_preceding_target_direction_more_strongly() -> None:
    base = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    source_offsets = [0, 2, 7, 13, 21, 30, 34, 47]
    source_times = [base + timedelta(minutes=offset) for offset in source_offsets]
    target_times = [timestamp + timedelta(minutes=1) for timestamp in source_times]
    series = build_count_series(
        {"A": source_times, "B": target_times},
        template_ids=["A", "B"],
        time_bin_seconds=60,
    )

    results = score_granger_pairs(
        series.series_by_template,
        ["A", "B"],
        time_bin_seconds=60,
        max_lag_bins=1,
    )
    forward = results[("A", "B")]
    reverse = results[("B", "A")]

    assert forward["supported"] is True
    assert forward["lag_bins"] == 1
    assert forward["lag_seconds"] == 60
    assert forward["p_value"] is not None
    assert forward["p_value_adj"] is not None
    assert forward["score"] > reverse["score"]
    assert reverse["supported"] is False


def test_sparse_and_constant_inputs_are_unsupported_not_errors() -> None:
    base = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)

    pgem = score_pgem_transition(
        [base],
        [base + timedelta(seconds=30)],
        max_lag_seconds=60,
    )
    granger = score_granger_pair(
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        time_bin_seconds=60,
        max_lag_bins=1,
    )

    assert pgem["supported"] is False
    assert pgem["reason"] == "too_few_events"
    assert granger["supported"] is False
    assert granger["reason"] in {"too_few_events", "constant_series"}


def test_benjamini_hochberg_adjustment_is_deterministic_and_monotonic() -> None:
    p_values = {
        ("A", "B"): 0.01,
        ("A", "C"): 0.04,
        ("B", "C"): 0.03,
        ("C", "A"): 0.20,
    }

    first = benjamini_hochberg(p_values)
    second = benjamini_hochberg(dict(reversed(list(p_values.items()))))

    assert first == second
    ordered_pairs = sorted(p_values, key=p_values.get)
    adjusted_in_p_order = [first[pair] for pair in ordered_pairs]
    assert adjusted_in_p_order == sorted(adjusted_in_p_order)
    assert all(first[pair] >= p_values[pair] for pair in p_values)
