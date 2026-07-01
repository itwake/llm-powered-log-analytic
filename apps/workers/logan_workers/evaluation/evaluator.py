from __future__ import annotations

import re
from pathlib import Path

from logan_workers.activities.inference import MockAIPlatformAnnotationGateway
from logan_workers.evaluation.benchmark import load_benchmark
from logan_workers.evaluation.metrics import (
    flatten_entities,
    multiclass_macro_f1,
    multilabel_micro_macro_f1,
    precision_recall_f1,
    review_load_reduction,
    weighted_average,
)
from logan_workers.evaluation.schemas import (
    BenchmarkEvaluationReport,
    EdgePatternEvaluation,
    ExpectedCausalEdgeLabel,
    ExpectedTemplateLabel,
    LoadedBenchmark,
    MetricScore,
    PipelineCountSummary,
    RootCauseCandidateEvaluation,
    RootCauseEvaluation,
    SummaryRubricEvaluation,
    TemplatePatternEvaluation,
)
from logan_workers.models import AnalysisResult, CausalEdge, LogTemplate, TemplateAnnotation
from logan_workers.pipeline import AnalyzeCasePipeline


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _match_template(pattern: str, templates: list[LogTemplate]) -> LogTemplate | None:
    matches = [template for template in templates if _matches(pattern, template.template_text)]
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda template: (
            template.first_seen is None,
            template.first_seen,
            template.template_text,
        ),
    )[0]


def _metric(
    name: str,
    value: float,
    thresholds: dict[str, float],
    *,
    details: dict | None = None,
) -> MetricScore:
    threshold = thresholds.get(name)
    return MetricScore(
        value=round(value, 6),
        threshold=threshold,
        passed=None if threshold is None else value >= threshold,
        details=details or {},
    )


def _evaluate_templates(
    *,
    labels: list[ExpectedTemplateLabel],
    result: AnalysisResult,
) -> tuple[
    list[TemplatePatternEvaluation],
    list[str | None],
    list[str | None],
    list[set[str]],
    list[set[str]],
    set[str],
    set[str],
]:
    annotations_by_template = {
        annotation.template_id: annotation for annotation in result.annotations
    }
    evaluations: list[TemplatePatternEvaluation] = []
    expected_golden: list[str | None] = []
    actual_golden: list[str | None] = []
    expected_faults: list[set[str]] = []
    actual_faults: list[set[str]] = []
    expected_entities: set[str] = set()
    actual_entities: set[str] = set()

    for label in labels:
        template = _match_template(label.template_pattern, result.templates)
        annotation: TemplateAnnotation | None = (
            annotations_by_template.get(template.template_id) if template else None
        )
        expected_golden.append(label.golden_signal)
        actual_golden.append(annotation.golden_signal if annotation else None)
        label_faults = set(label.fault_categories)
        annotation_faults = set(annotation.fault_categories if annotation else [])
        expected_faults.append(label_faults)
        actual_faults.append(annotation_faults)
        expected_entities |= flatten_entities(label.entities)
        if annotation:
            actual_entities |= flatten_entities(annotation.entities)

        evaluations.append(
            TemplatePatternEvaluation(
                label_id=label.id,
                expected_pattern=label.template_pattern,
                matched=template is not None,
                template_id=template.template_id if template else None,
                expected_golden_signal=label.golden_signal,
                actual_golden_signal=annotation.golden_signal if annotation else None,
                missing_fault_categories=sorted(label_faults - annotation_faults),
                extra_fault_categories=sorted(annotation_faults - label_faults),
            )
        )

    return (
        evaluations,
        expected_golden,
        actual_golden,
        expected_faults,
        actual_faults,
        expected_entities,
        actual_entities,
    )


def _evaluate_root_cause(
    result: AnalysisResult,
    patterns: list[str],
    top_k: int,
) -> RootCauseEvaluation:
    templates_by_id = {template.template_id: template for template in result.templates}
    candidates: list[RootCauseCandidateEvaluation] = []
    hit_rank: int | None = None
    for candidate in result.causal_graph.root_cause_candidates[:top_k]:
        template = templates_by_id[candidate.template_id]
        matched = [
            pattern
            for pattern in patterns
            if _matches(pattern, template.template_text)
        ]
        if matched and hit_rank is None:
            hit_rank = candidate.rank
        candidates.append(
            RootCauseCandidateEvaluation(
                rank=candidate.rank,
                template_id=candidate.template_id,
                matched_expected_patterns=matched,
            )
        )
    return RootCauseEvaluation(
        top_k=top_k,
        hit=hit_rank is not None,
        hit_rank=hit_rank,
        accepted_patterns=patterns,
        candidates=candidates,
    )


def _edge_matches_label(
    *,
    edge: CausalEdge,
    label: ExpectedCausalEdgeLabel,
    templates_by_id: dict[str, LogTemplate],
) -> bool:
    source = templates_by_id[edge.source_template_id].template_text
    target = templates_by_id[edge.target_template_id].template_text
    return _matches(label.source_pattern, source) and _matches(label.target_pattern, target)


def _evaluate_useful_edges(
    *,
    labels: list[ExpectedCausalEdgeLabel],
    result: AnalysisResult,
) -> list[EdgePatternEvaluation]:
    templates_by_id = {template.template_id: template for template in result.templates}
    evaluations: list[EdgePatternEvaluation] = []
    for label in labels:
        matched_edge = next(
            (
                edge
                for edge in result.causal_graph.edges
                if _edge_matches_label(edge=edge, label=label, templates_by_id=templates_by_id)
            ),
            None,
        )
        evaluations.append(
            EdgePatternEvaluation(
                label_id=label.id,
                source_pattern=label.source_pattern,
                target_pattern=label.target_pattern,
                matched=matched_edge is not None,
                edge_id=matched_edge.id if matched_edge else None,
                confidence=matched_edge.confidence if matched_edge else None,
                method=matched_edge.method if matched_edge else None,
            )
        )
    return evaluations


def _evaluate_summary_rubric(
    result: AnalysisResult,
    benchmark: LoadedBenchmark,
) -> tuple[list[SummaryRubricEvaluation], float]:
    summary = result.causal_summary
    next_action_text = "\n".join(
        f"{action.get('title', '')}\n{action.get('description', '')}"
        for action in summary.next_actions
    )
    text = "\n".join(
        [
            summary.summary_markdown,
            summary.customer_update_markdown,
            next_action_text,
        ]
    ).lower()

    evaluations: list[SummaryRubricEvaluation] = []
    weighted_scores: list[tuple[float, float]] = []
    for expectation in benchmark.labels.summary_rubric:
        terms = [term.lower() for term in expectation.required_terms]
        matched = [term for term in terms if term in text]
        missing = [term for term in terms if term not in text]
        score = len(matched) / len(terms)
        weighted_scores.append((score, expectation.weight))
        evaluations.append(
            SummaryRubricEvaluation(
                key=expectation.key,
                score=round(score, 6),
                weight=expectation.weight,
                matched_terms=matched,
                missing_terms=missing,
            )
        )
    return evaluations, weighted_average(weighted_scores)


async def run_benchmark_pipeline(benchmark: LoadedBenchmark) -> AnalysisResult:
    return await AnalyzeCasePipeline().run(
        case_id=benchmark.manifest.case_id,
        analysis_run_id=benchmark.manifest.analysis_run_id,
        paths=[str(path) for path in benchmark.input_paths],
        case_context=benchmark.manifest.case_context,
        config=benchmark.manifest.config,
        gateway=MockAIPlatformAnnotationGateway(),
    )


async def evaluate_benchmark(benchmark: LoadedBenchmark) -> BenchmarkEvaluationReport:
    result = await run_benchmark_pipeline(benchmark)
    labels = benchmark.labels

    (
        template_evaluations,
        expected_golden,
        actual_golden,
        expected_faults,
        actual_faults,
        expected_entities,
        actual_entities,
    ) = _evaluate_templates(labels=labels.expected_templates, result=result)

    golden_macro_f1, golden_per_label = multiclass_macro_f1(expected_golden, actual_golden)
    fault_scores = multilabel_micro_macro_f1(expected_faults, actual_faults)
    entity_scores = precision_recall_f1(expected_entities, actual_entities)

    root_cause = _evaluate_root_cause(
        result,
        labels.expected_root_cause.candidate_patterns,
        labels.expected_root_cause.top_k,
    )
    useful_edges = _evaluate_useful_edges(
        labels=labels.expected_useful_causal_edges,
        result=result,
    )
    useful_edge_hits = sum(1 for edge in useful_edges if edge.matched)
    useful_edge_recall = useful_edge_hits / len(useful_edges) if useful_edges else 1.0
    useful_edge_precision = (
        useful_edge_hits / len(result.causal_graph.edges)
        if result.causal_graph.edges
        else float(useful_edge_hits == 0)
    )

    summary_rubric, summary_score = _evaluate_summary_rubric(result, benchmark)

    root_metric_name = f"root_cause_hit_at_{labels.expected_root_cause.top_k}"
    thresholds = labels.thresholds
    metrics = {
        "review_load_reduction": _metric(
            "review_load_reduction",
            review_load_reduction(
                raw_items=len(result.raw_entries),
                review_items=len(result.samples),
            ),
            thresholds,
            details={
                "review_unit": "representative_sample",
                "raw_entries": len(result.raw_entries),
                "review_items": len(result.samples),
            },
        ),
        "golden_signal_macro_f1": _metric(
            "golden_signal_macro_f1",
            golden_macro_f1,
            thresholds,
            details={"per_label_f1": golden_per_label},
        ),
        "fault_category_micro_f1": _metric(
            "fault_category_micro_f1",
            fault_scores.micro.f1,
            thresholds,
            details={
                "precision": fault_scores.micro.precision,
                "recall": fault_scores.micro.recall,
                "true_positive": fault_scores.micro.true_positive,
                "false_positive": fault_scores.micro.false_positive,
                "false_negative": fault_scores.micro.false_negative,
            },
        ),
        "fault_category_macro_f1": _metric(
            "fault_category_macro_f1",
            fault_scores.macro_f1,
            thresholds,
            details={"per_label_f1": fault_scores.per_label_f1},
        ),
        "entity_precision": _metric(
            "entity_precision",
            entity_scores.precision,
            thresholds,
            details={"true_positive": entity_scores.true_positive},
        ),
        "entity_recall": _metric(
            "entity_recall",
            entity_scores.recall,
            thresholds,
            details={"false_negative": entity_scores.false_negative},
        ),
        "entity_f1": _metric(
            "entity_f1",
            entity_scores.f1,
            thresholds,
            details={
                "true_positive": entity_scores.true_positive,
                "false_positive": entity_scores.false_positive,
                "false_negative": entity_scores.false_negative,
            },
        ),
        root_metric_name: _metric(
            root_metric_name,
            1.0 if root_cause.hit else 0.0,
            thresholds,
            details={"hit_rank": root_cause.hit_rank},
        ),
        "useful_causal_edge_recall": _metric(
            "useful_causal_edge_recall",
            useful_edge_recall,
            thresholds,
            details={"hits": useful_edge_hits, "expected_edges": len(useful_edges)},
        ),
        "useful_causal_edge_precision": _metric(
            "useful_causal_edge_precision",
            useful_edge_precision,
            thresholds,
            details={"hits": useful_edge_hits, "produced_edges": len(result.causal_graph.edges)},
        ),
        "summary_rubric_score": _metric(
            "summary_rubric_score",
            summary_score,
            thresholds,
            details={"items": len(summary_rubric)},
        ),
    }

    threshold_results = [
        score.passed for score in metrics.values() if score.passed is not None
    ]
    status = "passed" if all(threshold_results) else "failed"

    return BenchmarkEvaluationReport(
        benchmark_id=benchmark.manifest.benchmark_id,
        benchmark_name=benchmark.manifest.name,
        case_id=benchmark.manifest.case_id,
        analysis_run_id=benchmark.manifest.analysis_run_id,
        status=status,
        metrics=metrics,
        pipeline_counts=PipelineCountSummary(
            raw_entries=len(result.raw_entries),
            normalized_logs=len(result.normalized_logs),
            templates=len(result.templates),
            samples=len(result.samples),
            annotations=len(result.annotations),
            causal_nodes=len(result.causal_graph.nodes),
            causal_edges=len(result.causal_graph.edges),
        ),
        template_patterns=template_evaluations,
        useful_causal_edges=useful_edges,
        root_cause=root_cause,
        summary_rubric=summary_rubric,
    )


async def evaluate_benchmark_path(benchmark_dir: str | Path) -> BenchmarkEvaluationReport:
    return await evaluate_benchmark(load_benchmark(benchmark_dir))
