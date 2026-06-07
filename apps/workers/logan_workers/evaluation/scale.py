from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import platform
import resource
import time
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from logan_workers.activities.inference import MockCopilotAnnotationGateway
from logan_workers.evaluation.metrics import review_load_reduction
from logan_workers.evaluation.reporting import ensure_report_text_is_safe
from logan_workers.evaluation.schemas import ReportSafetySummary
from logan_workers.pipeline import AnalyzeCasePipeline


PROFILE_TARGET_BYTES = {
    "quick": 64 * 1024,
    "1gb": 1 * 1024 * 1024 * 1024,
    "5gb": 5 * 1024 * 1024 * 1024,
}


@dataclass(frozen=True)
class GeneratedFixtureFile:
    name: str
    kind: str
    path: Path
    logical_bytes: int
    disk_bytes: int
    raw_lines: int
    archive_members: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GeneratedScaleFixture:
    fixture_id: str
    profile: str
    root: Path
    input_paths: list[Path]
    target_bytes: int
    logical_bytes: int
    disk_bytes: int
    raw_lines: int
    files: list[GeneratedFixtureFile]


class ScaleFixtureFileSummary(BaseModel):
    name: str
    kind: str
    logical_bytes: int
    disk_bytes: int
    raw_lines: int
    archive_members: list[str] = Field(default_factory=list)


class ScaleFixtureSummary(BaseModel):
    fixture_id: str
    profile: str
    target_bytes: int
    logical_bytes: int
    disk_bytes: int
    raw_lines: int
    input_file_count: int
    files: list[ScaleFixtureFileSummary]


class ScalePipelineCountSummary(BaseModel):
    raw_lines: int
    files: int
    raw_entries: int
    normalized_logs: int
    templates: int
    representative_samples: int
    annotations: int
    windows: int
    causal_nodes: int
    causal_edges: int


class ScalePerformanceSummary(BaseModel):
    wall_time_seconds: float
    peak_rss_bytes: int | None = None
    peak_rss_delta_bytes: int | None = None
    linux_peak_rss: bool


class ScaleCausalSummary(BaseModel):
    present: bool
    confidence: float
    evidence_refs: int
    next_actions: int
    summary_chars: int
    customer_update_chars: int


class ScaleBenchmarkReport(BaseModel):
    benchmark_id: str
    profile: str
    case_id: str
    analysis_run_id: str
    status: str
    generated_fixture: ScaleFixtureSummary
    pipeline_counts: ScalePipelineCountSummary
    performance: ScalePerformanceSummary
    model_call_count: int
    annotation_model_call_count: int
    summary_model_call_count: int
    review_load_reduction: float
    causal_summary: ScaleCausalSummary
    safety: ReportSafetySummary = Field(default_factory=ReportSafetySummary)


def _line_bytes(lines: Iterable[str]) -> int:
    return sum(len((line + "\n").encode("utf-8")) for line in lines)


def _event_lines(index: int) -> list[str]:
    base = datetime(2026, 6, 6, 10, 0, 0, tzinfo=UTC) + timedelta(seconds=index * 12)
    request_id = f"req-{index:08d}"
    trace_id = f"trace-{index:08d}"
    customer_id = f"customer-{index % 97:03d}"
    return [
        (
            f"{base.isoformat().replace('+00:00', 'Z')} INFO gateway "
            f"post /checkout started request_id={request_id} trace_id={trace_id} "
            f"tenant_id={customer_id}"
        ),
        (
            f"{(base + timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')} "
            f"WARN auth-service connection pool usage high db=db active={90 + index % 7} "
            f"max=100 request_id={request_id}"
        ),
        (
            f"{(base + timedelta(seconds=2)).isoformat().replace('+00:00', 'Z')} "
            f"ERROR auth-service connection pool exhausted db=db active=100 max=100 "
            f"request_id={request_id} token=fixture-{index:08d}"
        ),
        (
            f"{(base + timedelta(seconds=3)).isoformat().replace('+00:00', 'Z')} "
            f"ERROR auth-service failed to acquire db connection db=db timeout_ms=5000 "
            f"request_id={request_id}"
        ),
        (
            f"{(base + timedelta(seconds=4)).isoformat().replace('+00:00', 'Z')} "
            f"WARN payment-service retry attempt=2 calling auth-service "
            f"request_id={request_id} trace_id={trace_id}"
        ),
        (
            f"{(base + timedelta(seconds=5)).isoformat().replace('+00:00', 'Z')} "
            f"ERROR payment-service timeout calling auth-service duration_ms=30000 "
            f"request_id={request_id} trace_id={trace_id}"
        ),
        (
            f"{(base + timedelta(seconds=6)).isoformat().replace('+00:00', 'Z')} "
            f"ERROR gateway post /checkout failed status=500 duration_ms=31000 "
            f"request_id={request_id} trace_id={trace_id} Authorization=Bearer "
            f"fixture.{index:08d}.value"
        ),
        (
            f"{(base + timedelta(seconds=7)).isoformat().replace('+00:00', 'Z')} "
            f"ERROR payment-service timeout calling auth-service request_id={request_id} "
            "Traceback (most recent call last):"
        ),
        '  File "checkout.py", line 44, in authorize',
        "    raise TimeoutError('auth-service dependency timeout')",
        "TimeoutError: auth-service dependency timeout",
        (
            f"{(base + timedelta(seconds=8)).isoformat().replace('+00:00', 'Z')} "
            f"INFO inventory-service reservation completed sku=sku-{index % 13:03d} "
            f"request_id={request_id}"
        ),
    ]


def _jsonl_event_lines(index: int) -> list[str]:
    base = datetime(2026, 6, 6, 11, 0, 0, tzinfo=UTC) + timedelta(seconds=index * 12)
    request_id = f"req-json-{index:08d}"
    payloads = [
        {
            "timestamp": base.isoformat().replace("+00:00", "Z"),
            "level": "WARN",
            "service": "auth-service",
            "message": (
                "auth-service connection pool exhausted db=db active=100 max=100 "
                f"request_id={request_id}"
            ),
        },
        {
            "timestamp": (base + timedelta(seconds=3)).isoformat().replace("+00:00", "Z"),
            "level": "ERROR",
            "service": "payment-service",
            "message": (
                "payment-service timeout calling auth-service duration_ms=30000 "
                f"request_id={request_id}"
            ),
        },
        {
            "timestamp": (base + timedelta(seconds=6)).isoformat().replace("+00:00", "Z"),
            "level": "ERROR",
            "service": "gateway",
            "message": (
                "gateway post /checkout failed status=500 duration_ms=31000 "
                f"request_id={request_id}"
            ),
        },
    ]
    return [json.dumps(payload, sort_keys=True) for payload in payloads]


def _write_until(
    writer: Callable[[str], None],
    *,
    target_bytes: int,
    line_factory: Callable[[int], list[str]],
    start_index: int = 0,
) -> tuple[int, int, int]:
    logical_bytes = 0
    raw_lines = 0
    index = start_index
    while logical_bytes < target_bytes:
        lines = line_factory(index)
        for line in lines:
            writer(line)
        logical_bytes += _line_bytes(lines)
        raw_lines += len(lines)
        index += 1
    return logical_bytes, raw_lines, index


def _write_plain(path: Path, target_bytes: int, start_index: int) -> tuple[int, int, int]:
    with path.open("w", encoding="utf-8") as handle:
        return _write_until(
            lambda line: handle.write(line + "\n"),
            target_bytes=target_bytes,
            line_factory=_event_lines,
            start_index=start_index,
        )


def _write_jsonl(path: Path, target_bytes: int, start_index: int) -> tuple[int, int, int]:
    with path.open("w", encoding="utf-8") as handle:
        return _write_until(
            lambda line: handle.write(line + "\n"),
            target_bytes=target_bytes,
            line_factory=_jsonl_event_lines,
            start_index=start_index,
        )


def _write_gzip(path: Path, target_bytes: int, start_index: int) -> tuple[int, int, int]:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        return _write_until(
            lambda line: handle.write(line + "\n"),
            target_bytes=target_bytes,
            line_factory=_event_lines,
            start_index=start_index,
        )


def _write_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    target_bytes: int,
    line_factory: Callable[[int], list[str]],
    start_index: int,
) -> tuple[int, int, int]:
    with archive.open(name, "w") as handle:
        return _write_until(
            lambda line: handle.write((line + "\n").encode("utf-8")),
            target_bytes=target_bytes,
            line_factory=line_factory,
            start_index=start_index,
        )


def _write_zip(path: Path, target_bytes: int, start_index: int) -> tuple[int, int, int, list[str]]:
    member_target = max(1, target_bytes // 2)
    members = ["region-a/auth-payment.log", "region-b/gateway.jsonl"]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        auth_bytes, auth_lines, next_index = _write_zip_member(
            archive,
            members[0],
            target_bytes=member_target,
            line_factory=_event_lines,
            start_index=start_index,
        )
        gateway_bytes, gateway_lines, next_index = _write_zip_member(
            archive,
            members[1],
            target_bytes=target_bytes - member_target,
            line_factory=_jsonl_event_lines,
            start_index=next_index,
        )
    return auth_bytes + gateway_bytes, auth_lines + gateway_lines, next_index, members


def generate_scale_fixture(
    *,
    output_dir: str | Path = ".logan/scale-fixtures",
    profile: str = "quick",
    target_bytes: int | None = None,
) -> GeneratedScaleFixture:
    if profile not in PROFILE_TARGET_BYTES:
        allowed = ", ".join(sorted(PROFILE_TARGET_BYTES))
        raise ValueError(f"unknown scale profile {profile!r}; expected one of: {allowed}")
    target = target_bytes or PROFILE_TARGET_BYTES[profile]
    if target <= 0:
        raise ValueError("target_bytes must be positive")

    fixture_id = f"logan-scale-{profile}-{target}"
    root = Path(output_dir) / fixture_id
    root.mkdir(parents=True, exist_ok=True)

    share = max(1, target // 4)
    specs = [
        ("checkout-plain.log", "plain_log", share, _write_plain),
        ("checkout-jsonl.jsonl", "jsonl", share, _write_jsonl),
        ("checkout-gzip.log.gz", "gzip_log", share, _write_gzip),
    ]

    files: list[GeneratedFixtureFile] = []
    input_paths: list[Path] = []
    logical_total = 0
    raw_line_total = 0
    next_index = 0

    for name, kind, size, writer in specs:
        path = root / name
        logical_bytes, raw_lines, next_index = writer(path, size, next_index)
        disk_bytes = path.stat().st_size
        files.append(
            GeneratedFixtureFile(
                name=name,
                kind=kind,
                path=path,
                logical_bytes=logical_bytes,
                disk_bytes=disk_bytes,
                raw_lines=raw_lines,
            )
        )
        input_paths.append(path)
        logical_total += logical_bytes
        raw_line_total += raw_lines

    zip_path = root / "checkout-archive.zip"
    zip_bytes, zip_lines, next_index, members = _write_zip(
        zip_path,
        max(1, target - logical_total),
        next_index,
    )
    files.append(
        GeneratedFixtureFile(
            name=zip_path.name,
            kind="zip_archive",
            path=zip_path,
            logical_bytes=zip_bytes,
            disk_bytes=zip_path.stat().st_size,
            raw_lines=zip_lines,
            archive_members=members,
        )
    )
    input_paths.append(zip_path)
    logical_total += zip_bytes
    raw_line_total += zip_lines

    return GeneratedScaleFixture(
        fixture_id=fixture_id,
        profile=profile,
        root=root,
        input_paths=input_paths,
        target_bytes=target,
        logical_bytes=logical_total,
        disk_bytes=sum(file.disk_bytes for file in files),
        raw_lines=raw_line_total,
        files=files,
    )


def _fixture_summary(fixture: GeneratedScaleFixture) -> ScaleFixtureSummary:
    return ScaleFixtureSummary(
        fixture_id=fixture.fixture_id,
        profile=fixture.profile,
        target_bytes=fixture.target_bytes,
        logical_bytes=fixture.logical_bytes,
        disk_bytes=fixture.disk_bytes,
        raw_lines=fixture.raw_lines,
        input_file_count=len(fixture.input_paths),
        files=[
            ScaleFixtureFileSummary(
                name=file.name,
                kind=file.kind,
                logical_bytes=file.logical_bytes,
                disk_bytes=file.disk_bytes,
                raw_lines=file.raw_lines,
                archive_members=file.archive_members,
            )
            for file in fixture.files
        ],
    )


def _peak_rss_bytes() -> int | None:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if usage <= 0:
        return None
    if platform.system().lower() == "darwin":
        return int(usage)
    return int(usage) * 1024


def _current_rss_bytes_linux() -> int | None:
    status_path = Path("/proc/self/status")
    if not status_path.exists():
        return None
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return None


def _model_call_counts(calls: list[dict[str, Any]]) -> tuple[int, int]:
    annotation_calls = 0
    summary_calls = 0
    for call in calls:
        metadata = call.get("metadata") if isinstance(call.get("metadata"), dict) else {}
        purpose = metadata.get("purpose")
        if purpose == "template_annotation":
            annotation_calls += 1
        elif purpose == "causal_summary":
            summary_calls += 1
    return annotation_calls, summary_calls


async def run_scale_benchmark(
    *,
    profile: str = "quick",
    fixture_dir: str | Path = ".logan/scale-fixtures",
    target_bytes: int | None = None,
) -> ScaleBenchmarkReport:
    fixture = generate_scale_fixture(
        output_dir=fixture_dir,
        profile=profile,
        target_bytes=target_bytes,
    )
    gateway = MockCopilotAnnotationGateway()
    case_id = f"{fixture.fixture_id}-case"
    analysis_run_id = f"{fixture.fixture_id}-run"
    baseline_rss = _current_rss_bytes_linux()
    started_at = time.perf_counter()
    result = await AnalyzeCasePipeline().run(
        case_id=case_id,
        analysis_run_id=analysis_run_id,
        paths=[str(path) for path in fixture.input_paths],
        case_context={
            "title": "Synthetic checkout scale incident",
            "issue_description": "Cross-service checkout failures during dependency saturation.",
            "product": "commerce-platform",
            "environment": "scale-benchmark",
        },
        config={
            "default_window_size_seconds": 60,
            "causal": {
                "max_lag_seconds": 600,
                "time_bin_seconds": 60,
                "granger_max_lag_bins": 10,
                "methods": [
                    "temporal_precedence",
                    "lagged_correlation",
                    "lift",
                    "pgem",
                    "granger_linear",
                ],
            },
        },
        gateway=gateway,
    )
    wall_time = time.perf_counter() - started_at
    peak_rss = _peak_rss_bytes()
    peak_delta = (
        max(0, peak_rss - baseline_rss)
        if peak_rss is not None and baseline_rss is not None
        else None
    )
    annotation_call_count, summary_call_count = _model_call_counts(gateway.calls)

    report = ScaleBenchmarkReport(
        benchmark_id="logan.scale.synthetic",
        profile=profile,
        case_id=case_id,
        analysis_run_id=analysis_run_id,
        status="completed",
        generated_fixture=_fixture_summary(fixture),
        pipeline_counts=ScalePipelineCountSummary(
            raw_lines=sum(len(file.lines) for file in result.files),
            files=len(result.files),
            raw_entries=len(result.raw_entries),
            normalized_logs=len(result.normalized_logs),
            templates=len(result.templates),
            representative_samples=len(result.samples),
            annotations=len(result.annotations),
            windows=len(result.temporal),
            causal_nodes=len(result.causal_graph.nodes),
            causal_edges=len(result.causal_graph.edges),
        ),
        performance=ScalePerformanceSummary(
            wall_time_seconds=round(wall_time, 6),
            peak_rss_bytes=peak_rss,
            peak_rss_delta_bytes=peak_delta,
            linux_peak_rss=platform.system().lower() == "linux",
        ),
        model_call_count=len(gateway.calls),
        annotation_model_call_count=annotation_call_count,
        summary_model_call_count=summary_call_count,
        review_load_reduction=review_load_reduction(
            raw_items=len(result.raw_entries),
            review_items=len(result.samples),
        ),
        causal_summary=ScaleCausalSummary(
            present=bool(result.causal_summary.summary_markdown),
            confidence=result.causal_summary.confidence,
            evidence_refs=len(result.causal_summary.evidence_refs),
            next_actions=len(result.causal_summary.next_actions),
            summary_chars=len(result.causal_summary.summary_markdown),
            customer_update_chars=len(result.causal_summary.customer_update_markdown),
        ),
    )
    ensure_report_text_is_safe(scale_report_to_json(report))
    return report


def scale_report_to_json(report: ScaleBenchmarkReport) -> str:
    text = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)
    ensure_report_text_is_safe(text)
    return text


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


def scale_report_to_markdown(report: ScaleBenchmarkReport) -> str:
    lines = [
        "# LogAn Scale Benchmark",
        "",
        f"Benchmark: `{report.benchmark_id}`",
        f"Profile: `{report.profile}`",
        f"Case: `{report.case_id}`",
        f"Analysis run: `{report.analysis_run_id}`",
        f"Status: `{report.status}`",
        "",
        "## Fixture",
        "",
        "| Item | Value |",
        "| --- | ---: |",
        f"| Target bytes | {report.generated_fixture.target_bytes} |",
        f"| Logical bytes | {report.generated_fixture.logical_bytes} |",
        f"| Disk bytes | {report.generated_fixture.disk_bytes} |",
        f"| Raw lines | {report.generated_fixture.raw_lines} |",
        f"| Input files | {report.generated_fixture.input_file_count} |",
        "",
        "## Fixture Files",
        "",
        "| Name | Kind | Logical bytes | Disk bytes | Raw lines |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for item in report.generated_fixture.files:
        lines.append(
            f"| `{item.name}` | `{item.kind}` | {item.logical_bytes} | "
            f"{item.disk_bytes} | {item.raw_lines} |"
        )

    lines.extend(
        [
            "",
            "## Pipeline Counts",
            "",
            "| Count | Value |",
            "| --- | ---: |",
            f"| Raw lines | {report.pipeline_counts.raw_lines} |",
            f"| Files | {report.pipeline_counts.files} |",
            f"| Source entries | {report.pipeline_counts.raw_entries} |",
            f"| Normalized logs | {report.pipeline_counts.normalized_logs} |",
            f"| Templates | {report.pipeline_counts.templates} |",
            f"| Representative samples | {report.pipeline_counts.representative_samples} |",
            f"| Annotations | {report.pipeline_counts.annotations} |",
            f"| Windows | {report.pipeline_counts.windows} |",
            f"| Causal nodes | {report.pipeline_counts.causal_nodes} |",
            f"| Causal edges | {report.pipeline_counts.causal_edges} |",
            "",
            "## Runtime",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Wall time seconds | {report.performance.wall_time_seconds:.6f} |",
            f"| Peak RSS bytes | {_format_bytes(report.performance.peak_rss_bytes)} |",
            f"| Peak RSS delta bytes | {_format_bytes(report.performance.peak_rss_delta_bytes)} |",
            f"| Model calls | {report.model_call_count} |",
            f"| Annotation model calls | {report.annotation_model_call_count} |",
            f"| Summary model calls | {report.summary_model_call_count} |",
            f"| Review-load reduction | {report.review_load_reduction:.6f} |",
            "",
            "## Causal Summary",
            "",
            "| Item | Value |",
            "| --- | ---: |",
            f"| Present | `{str(report.causal_summary.present).lower()}` |",
            f"| Confidence | {report.causal_summary.confidence:.4f} |",
            f"| Evidence refs | {report.causal_summary.evidence_refs} |",
            f"| Next actions | {report.causal_summary.next_actions} |",
            f"| Summary chars | {report.causal_summary.summary_chars} |",
            f"| Customer update chars | {report.causal_summary.customer_update_chars} |",
        ]
    )
    text = "\n".join(lines) + "\n"
    ensure_report_text_is_safe(text)
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LogAn synthetic scale benchmark.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_TARGET_BYTES),
        default="quick",
        help="Fixture size profile. Defaults to quick.",
    )
    parser.add_argument(
        "--target-bytes",
        type=int,
        help="Override the profile's logical uncompressed fixture size.",
    )
    parser.add_argument(
        "--fixture-dir",
        default=".logan/scale-fixtures",
        help="Directory for generated fixture files. The default is gitignored.",
    )
    parser.add_argument("--out", required=True, help="Path for the JSON scale report.")
    parser.add_argument("--markdown", help="Optional path for the Markdown scale report.")
    return parser


async def _run(args: argparse.Namespace) -> int:
    report = await run_scale_benchmark(
        profile=args.profile,
        fixture_dir=args.fixture_dir,
        target_bytes=args.target_bytes,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scale_report_to_json(report) + "\n", encoding="utf-8")

    if args.markdown:
        markdown_path = Path(args.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(scale_report_to_markdown(report), encoding="utf-8")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
