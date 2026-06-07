from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from logan_workers.algorithms.causal_series import clamp_score


EPSILON = 1e-9


def _round_optional(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _unsupported(
    reason: str,
    *,
    lag_bins: int | None = None,
    time_bin_seconds: int,
    sample_size: int = 0,
    p_value: float | None = None,
    p_value_adj: float | None = None,
    score: float = 0.0,
) -> dict[str, Any]:
    return {
        "supported": False,
        "score": round(clamp_score(score), 6),
        "lag_bins": lag_bins,
        "lag_seconds": lag_bins * time_bin_seconds if lag_bins is not None else None,
        "p_value": _round_optional(p_value),
        "p_value_adj": _round_optional(p_value_adj),
        "sample_size": sample_size,
        "method": "ols_fallback",
        "reason": reason,
    }


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]

    for column in range(size):
        pivot_row = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot_row][column]) < EPSILON:
            return None
        if pivot_row != column:
            augmented[column], augmented[pivot_row] = augmented[pivot_row], augmented[column]

        pivot = augmented[column][column]
        for item in range(column, size + 1):
            augmented[column][item] /= pivot

        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            for item in range(column, size + 1):
                augmented[row][item] -= factor * augmented[column][item]

    return [augmented[row][size] for row in range(size)]


def _ols_sse(features: list[list[float]], values: list[float]) -> float | None:
    if not features or not values or len(features) != len(values):
        return None
    width = len(features[0])
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for row, value in zip(features, values):
        for left in range(width):
            xty[left] += row[left] * value
            for right in range(width):
                xtx[left][right] += row[left] * row[right]

    for index in range(width):
        xtx[index][index] += 1e-8

    coefficients = _solve_linear_system(xtx, xty)
    if coefficients is None:
        return None

    sse = 0.0
    for row, value in zip(features, values):
        prediction = sum(coefficient * item for coefficient, item in zip(coefficients, row))
        sse += (value - prediction) ** 2
    return max(0.0, sse)


def _regularized_gamma_q(a: float, x: float) -> float:
    if x < 0.0 or a <= 0.0:
        return 1.0
    if x == 0.0:
        return 1.0

    gln = math.lgamma(a)
    if x < a + 1.0:
        ap = a
        total = 1.0 / a
        delta = total
        for _ in range(100):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 3e-7:
                break
        p_value = total * math.exp(-x + a * math.log(x) - gln)
        return clamp_score(1.0 - p_value)

    b = x + 1.0 - a
    c = 1.0 / 1e-30
    d = 1.0 / b
    h = d
    for index in range(1, 101):
        an = -index * (index - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-7:
            break
    return clamp_score(math.exp(-x + a * math.log(x) - gln) * h)


def _chi_square_sf(statistic: float, degrees_of_freedom: int) -> float:
    if statistic <= 0.0 or degrees_of_freedom <= 0:
        return 1.0
    return _regularized_gamma_q(degrees_of_freedom / 2.0, statistic / 2.0)


def _lagged_design(
    source_counts: Sequence[int],
    target_counts: Sequence[int],
    lag_bins: int,
) -> tuple[list[float], list[list[float]], list[list[float]]]:
    values: list[float] = []
    baseline_features: list[list[float]] = []
    full_features: list[list[float]] = []
    for index in range(lag_bins, len(target_counts)):
        target_history = [float(target_counts[index - lag]) for lag in range(1, lag_bins + 1)]
        source_history = [float(source_counts[index - lag]) for lag in range(1, lag_bins + 1)]
        baseline = [1.0, *target_history]
        values.append(float(target_counts[index]))
        baseline_features.append(baseline)
        full_features.append([*baseline, *source_history])
    return values, baseline_features, full_features


def score_granger_pair(
    source_counts: Sequence[int],
    target_counts: Sequence[int],
    *,
    time_bin_seconds: int,
    max_lag_bins: int,
    min_events: int = 3,
    min_samples: int = 8,
    min_improvement: float = 0.10,
    alpha: float = 0.2,
) -> dict[str, Any]:
    if time_bin_seconds <= 0:
        time_bin_seconds = 60
    if max_lag_bins <= 0:
        return _unsupported(
            "invalid_max_lag",
            time_bin_seconds=time_bin_seconds,
        )
    if len(source_counts) != len(target_counts):
        return _unsupported(
            "series_length_mismatch",
            time_bin_seconds=time_bin_seconds,
        )
    if len(source_counts) < min_samples + 1:
        return _unsupported(
            "too_few_samples",
            time_bin_seconds=time_bin_seconds,
            sample_size=max(0, len(source_counts) - 1),
        )
    if sum(source_counts) < min_events or sum(target_counts) < min_events:
        return _unsupported(
            "too_few_events",
            time_bin_seconds=time_bin_seconds,
            sample_size=max(0, len(source_counts) - 1),
        )
    if len(set(source_counts)) < 2 or len(set(target_counts)) < 2:
        return _unsupported(
            "constant_series",
            time_bin_seconds=time_bin_seconds,
            sample_size=max(0, len(source_counts) - 1),
        )

    best: dict[str, Any] | None = None
    tested_any = False
    for lag_bins in range(1, max_lag_bins + 1):
        values, baseline_features, full_features = _lagged_design(
            source_counts,
            target_counts,
            lag_bins,
        )
        sample_size = len(values)
        if sample_size < max(min_samples, (2 * lag_bins) + 3):
            continue
        if len(set(values)) < 2:
            continue

        tested_any = True
        baseline_sse = _ols_sse(baseline_features, values)
        full_sse = _ols_sse(full_features, values)
        if baseline_sse is None or full_sse is None:
            continue
        improvement = max(0.0, baseline_sse - full_sse)
        improvement_ratio = improvement / max(baseline_sse, EPSILON)
        likelihood_ratio = (
            sample_size * math.log((baseline_sse + EPSILON) / (full_sse + EPSILON))
            if improvement > 0
            else 0.0
        )
        p_value = _chi_square_sf(likelihood_ratio, lag_bins)
        score = clamp_score(0.75 * improvement_ratio + 0.25 * (1.0 - p_value))
        candidate = {
            "supported": improvement_ratio >= min_improvement and p_value <= alpha,
            "score": round(score, 6),
            "lag_bins": lag_bins,
            "lag_seconds": lag_bins * time_bin_seconds,
            "p_value": round(p_value, 6),
            "p_value_adj": None,
            "sample_size": sample_size,
            "method": "ols_fallback",
            "baseline_sse": round(baseline_sse, 6),
            "full_sse": round(full_sse, 6),
            "improvement_ratio": round(improvement_ratio, 6),
            "likelihood_ratio": round(likelihood_ratio, 6),
        }
        if not candidate["supported"]:
            candidate["reason"] = (
                "weak_lagged_improvement"
                if improvement_ratio < min_improvement
                else "not_significant"
            )
        candidate_p_value = (
            float(candidate["p_value"]) if candidate.get("p_value") is not None else 1.0
        )
        best_p_value = float(best["p_value"]) if best and best.get("p_value") is not None else 1.0
        if best is None or (
            candidate["score"],
            -candidate_p_value,
            -candidate["lag_bins"],
        ) > (
            best["score"],
            -best_p_value,
            -best["lag_bins"],
        ):
            best = candidate

    if best is None:
        return _unsupported(
            "too_few_lagged_samples" if not tested_any else "model_fit_failed",
            time_bin_seconds=time_bin_seconds,
            sample_size=max(0, len(source_counts) - 1),
        )
    return best


def benjamini_hochberg(p_values: Mapping[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    if not p_values:
        return {}

    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0][0], item[0][1]))
    adjusted_ordered: list[tuple[tuple[str, str], float]] = []
    running_min = 1.0
    total = len(ordered)
    for rank_from_end, (pair, p_value) in enumerate(reversed(ordered), start=1):
        rank = total - rank_from_end + 1
        adjusted = min(running_min, max(0.0, min(1.0, p_value)) * total / rank)
        running_min = adjusted
        adjusted_ordered.append((pair, adjusted))
    return {pair: round(value, 6) for pair, value in adjusted_ordered}


def score_granger_pairs(
    series_by_template: Mapping[str, Sequence[int]],
    template_ids: Sequence[str],
    *,
    time_bin_seconds: int,
    max_lag_bins: int,
    alpha: float = 0.2,
) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for source_id in template_ids:
        for target_id in template_ids:
            if source_id == target_id:
                continue
            results[(source_id, target_id)] = score_granger_pair(
                series_by_template.get(source_id, []),
                series_by_template.get(target_id, []),
                time_bin_seconds=time_bin_seconds,
                max_lag_bins=max_lag_bins,
                alpha=alpha,
            )

    adjusted = benjamini_hochberg(
        {
            pair: float(evidence["p_value"])
            for pair, evidence in results.items()
            if evidence.get("p_value") is not None
        }
    )
    for pair, p_value_adj in adjusted.items():
        evidence = dict(results[pair])
        evidence["p_value_adj"] = p_value_adj
        if evidence.get("supported") and p_value_adj > alpha:
            evidence["supported"] = False
            evidence["reason"] = "not_significant_after_fdr"
        results[pair] = evidence

    return results
