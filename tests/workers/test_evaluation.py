from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from logan_workers.evaluation.benchmark import load_benchmark
from logan_workers.evaluation.metrics import (
    multiclass_macro_f1,
    multilabel_micro_macro_f1,
    precision_recall_f1,
    review_load_reduction,
)
from logan_workers.evaluation.reporting import (
    find_unsafe_report_terms,
    report_to_json,
    report_to_markdown,
)
from logan_workers.evaluation.run import main as evaluation_main
from logan_workers.evaluation.schemas import BenchmarkLabels


BENCHMARK_DIR = Path("benchmarks/logan/checkout_incident")


def test_metric_calculations_cover_perfect_partial_and_empty_cases() -> None:
    perfect_macro, perfect_labels = multiclass_macro_f1(
        ["error", "availability"],
        ["error", "availability"],
    )
    assert perfect_macro == 1.0
    assert perfect_labels == {"availability": 1.0, "error": 1.0}

    partial_macro, partial_labels = multiclass_macro_f1(
        ["error", "availability"],
        ["error", "error"],
    )
    assert 0.0 < partial_macro < 1.0
    assert partial_labels["availability"] == 0.0

    multilabel = multilabel_micro_macro_f1(
        [{"database", "timeout"}],
        [{"database", "resource"}],
    )
    assert multilabel.micro.precision == 0.5
    assert multilabel.micro.recall == 0.5
    assert multilabel.micro.f1 == 0.5
    assert 0.0 < multilabel.macro_f1 < 1.0

    empty = precision_recall_f1(set(), set())
    assert empty.precision == 1.0
    assert empty.recall == 1.0
    assert empty.f1 == 1.0
    assert review_load_reduction(raw_items=10, review_items=3) == 0.7


def test_benchmark_label_loading_and_regex_validation() -> None:
    benchmark = load_benchmark(BENCHMARK_DIR)
    assert benchmark.manifest.benchmark_id == "logan.checkout_incident"
    assert len(benchmark.input_paths) == 3
    assert len(benchmark.labels.expected_templates) == 6
    assert benchmark.labels.expected_root_cause.top_k == 3

    with pytest.raises(ValidationError):
        BenchmarkLabels.model_validate(
            {
                "expected_offending_template_patterns": ["["],
                "expected_templates": [
                    {
                        "id": "bad",
                        "template_pattern": "[",
                        "golden_signal": "error",
                        "fault_categories": [],
                        "entities": {},
                        "offending": True,
                    }
                ],
                "expected_root_cause": {
                    "candidate_patterns": ["error"],
                    "top_k": 1,
                },
                "expected_useful_causal_edges": [
                    {
                        "id": "edge",
                        "source_pattern": "source",
                        "target_pattern": "target",
                    }
                ],
                "summary_rubric": [
                    {
                        "key": "candidate",
                        "description": "Candidate language is present.",
                        "required_terms": ["candidate"],
                    }
                ],
            }
        )


def test_checkout_benchmark_cli_writes_safe_reports(tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    exit_code = evaluation_main(
        [
            "--benchmark",
            str(BENCHMARK_DIR),
            "--out",
            str(json_path),
            "--markdown",
            str(markdown_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["metrics"]["golden_signal_macro_f1"]["value"] == 1.0
    assert payload["metrics"]["fault_category_micro_f1"]["value"] == 1.0
    assert payload["metrics"]["entity_f1"]["value"] == 1.0
    assert payload["metrics"]["root_cause_hit_at_3"]["value"] == 1.0
    assert payload["metrics"]["useful_causal_edge_recall"]["value"] == 1.0
    assert payload["metrics"]["summary_rubric_score"]["value"] == 1.0
    assert payload["pipeline_counts"]["raw_entries"] == 9
    assert payload["pipeline_counts"]["templates"] == 6

    json_text = json_path.read_text(encoding="utf-8")
    markdown_text = markdown_path.read_text(encoding="utf-8")
    assert find_unsafe_report_terms(json_text) == []
    assert find_unsafe_report_terms(markdown_text) == []
    for forbidden in (
        "raw_message",
        "raw_text",
        "template_text",
        "model_inputs",
        "Authorization",
        "Bearer",
        "password",
        str(Path.cwd()),
    ):
        assert forbidden not in json_text
        assert forbidden not in markdown_text


@pytest.mark.asyncio
async def test_report_renderers_reject_sensitive_content() -> None:
    benchmark = load_benchmark(BENCHMARK_DIR)
    from logan_workers.evaluation.evaluator import evaluate_benchmark

    report = await evaluate_benchmark(benchmark)
    assert report_to_json(report)
    assert report_to_markdown(report)

    issues = find_unsafe_report_terms(
        "Authorization: Bearer value password=x raw_message=/root/workspace/source.log"
    )
    assert set(issues) == {"absolute_path", "raw_or_prompt_field", "sensitive_term"}
