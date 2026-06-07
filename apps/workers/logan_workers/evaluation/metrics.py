from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PrecisionRecallF1:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int


@dataclass(frozen=True)
class MultilabelScores:
    micro: PrecisionRecallF1
    macro_f1: float
    per_label_f1: dict[str, float]


def _normalize_label(value: str) -> str:
    return value.strip().lower()


def _prf(*, true_positive: int, false_positive: int, false_negative: int) -> PrecisionRecallF1:
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 1.0
    recall = true_positive / recall_denominator if recall_denominator else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return PrecisionRecallF1(
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def precision_recall_f1(expected: set[str], predicted: set[str]) -> PrecisionRecallF1:
    normalized_expected = {_normalize_label(item) for item in expected if item}
    normalized_predicted = {_normalize_label(item) for item in predicted if item}
    true_positive = len(normalized_expected & normalized_predicted)
    false_positive = len(normalized_predicted - normalized_expected)
    false_negative = len(normalized_expected - normalized_predicted)
    return _prf(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def multiclass_macro_f1(
    expected_labels: Sequence[str | None],
    predicted_labels: Sequence[str | None],
) -> tuple[float, dict[str, float]]:
    if len(expected_labels) != len(predicted_labels):
        raise ValueError("expected_labels and predicted_labels must have the same length")
    expected = [_normalize_label(label) if label else None for label in expected_labels]
    predicted = [_normalize_label(label) if label else None for label in predicted_labels]
    labels = sorted({label for label in expected + predicted if label})
    if not labels:
        return 1.0, {}

    per_label: dict[str, float] = {}
    for label in labels:
        true_positive = sum(
            1
            for expected_item, predicted_item in zip(expected, predicted)
            if expected_item == predicted_item == label
        )
        false_positive = sum(
            1
            for expected_item, predicted_item in zip(expected, predicted)
            if expected_item != label and predicted_item == label
        )
        false_negative = sum(
            1
            for expected_item, predicted_item in zip(expected, predicted)
            if expected_item == label and predicted_item != label
        )
        per_label[label] = _prf(
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
        ).f1
    macro = sum(per_label.values()) / len(per_label)
    return round(macro, 6), per_label


def multilabel_micro_macro_f1(
    expected_sets: Sequence[set[str]],
    predicted_sets: Sequence[set[str]],
) -> MultilabelScores:
    if len(expected_sets) != len(predicted_sets):
        raise ValueError("expected_sets and predicted_sets must have the same length")
    expected = [{_normalize_label(item) for item in items if item} for items in expected_sets]
    predicted = [{_normalize_label(item) for item in items if item} for items in predicted_sets]
    labels = sorted({item for items in expected + predicted for item in items})
    if not labels:
        perfect = PrecisionRecallF1(
            precision=1.0,
            recall=1.0,
            f1=1.0,
            true_positive=0,
            false_positive=0,
            false_negative=0,
        )
        return MultilabelScores(micro=perfect, macro_f1=1.0, per_label_f1={})

    total_true_positive = 0
    total_false_positive = 0
    total_false_negative = 0
    per_label: dict[str, float] = {}
    for label in labels:
        true_positive = sum(
            1
            for expected_items, predicted_items in zip(expected, predicted)
            if label in expected_items and label in predicted_items
        )
        false_positive = sum(
            1
            for expected_items, predicted_items in zip(expected, predicted)
            if label not in expected_items and label in predicted_items
        )
        false_negative = sum(
            1
            for expected_items, predicted_items in zip(expected, predicted)
            if label in expected_items and label not in predicted_items
        )
        total_true_positive += true_positive
        total_false_positive += false_positive
        total_false_negative += false_negative
        per_label[label] = _prf(
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
        ).f1

    macro = sum(per_label.values()) / len(per_label)
    return MultilabelScores(
        micro=_prf(
            true_positive=total_true_positive,
            false_positive=total_false_positive,
            false_negative=total_false_negative,
        ),
        macro_f1=round(macro, 6),
        per_label_f1=per_label,
    )


def flatten_entities(entities: Mapping[str, Sequence[str]]) -> set[str]:
    flattened: set[str] = set()
    for key, values in entities.items():
        normalized_key = _normalize_label(str(key))
        for value in values:
            normalized_value = _normalize_label(str(value))
            if normalized_key and normalized_value:
                flattened.add(f"{normalized_key}={normalized_value}")
    return flattened


def review_load_reduction(*, raw_items: int, review_items: int) -> float:
    if raw_items <= 0:
        return 0.0
    reduction = 1.0 - (max(0, review_items) / raw_items)
    return round(max(0.0, min(1.0, reduction)), 6)


def weighted_average(scores: Sequence[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in scores)
    if total_weight <= 0:
        return 0.0
    return round(sum(score * weight for score, weight in scores) / total_weight, 6)
