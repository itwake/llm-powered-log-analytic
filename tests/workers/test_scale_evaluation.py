from __future__ import annotations

import gzip
import json
import zipfile
from pathlib import Path

from logan_workers.evaluation.reporting import (
    find_unsafe_report_terms,
)
from logan_workers.evaluation.scale import (
    generate_scale_fixture,
    main as scale_main,
)


def test_scale_fixture_generator_mixes_formats_without_committing_fixture(tmp_path: Path) -> None:
    fixture = generate_scale_fixture(
        output_dir=tmp_path / "fixtures",
        profile="quick",
        target_bytes=24_000,
    )

    assert fixture.root.is_dir()
    assert fixture.logical_bytes >= 24_000
    assert fixture.raw_lines > 0
    assert len(fixture.input_paths) == 4
    assert {file.kind for file in fixture.files} == {
        "plain_log",
        "jsonl",
        "gzip_log",
        "zip_archive",
    }
    assert ".logan/" in Path(".gitignore").read_text(encoding="utf-8")

    plain = (fixture.root / "checkout-plain.log").read_text(encoding="utf-8")
    assert "payment-service timeout calling auth-service" in plain
    assert "Traceback (most recent call last):" in plain
    assert "token=fixture-" in plain

    with gzip.open(fixture.root / "checkout-gzip.log.gz", "rt", encoding="utf-8") as handle:
        gzip_text = handle.read()
    assert "auth-service connection pool exhausted" in gzip_text

    with zipfile.ZipFile(fixture.root / "checkout-archive.zip") as archive:
        names = sorted(archive.namelist())
        assert names == ["region-a/auth-payment.log", "region-b/gateway.jsonl"]
        json_line = archive.read("region-b/gateway.jsonl").decode("utf-8").splitlines()[0]
    assert json.loads(json_line)["service"] == "auth-service"


def test_report_sanitizer_rejects_scale_leak_shapes() -> None:
    unsafe = (
        "template_text=/root/workspace/source.log raw_message='line body' "
        "Authorization=Bearer value password=hunter2 token=abc"
    )
    assert set(find_unsafe_report_terms(unsafe)) == {
        "absolute_path",
        "raw_or_prompt_field",
        "sensitive_term",
    }


def test_scale_benchmark_cli_quick_profile_writes_safe_reports(tmp_path: Path) -> None:
    json_path = tmp_path / "scale.json"
    markdown_path = tmp_path / "scale.md"

    exit_code = scale_main(
        [
            "--profile",
            "quick",
            "--target-bytes",
            "32768",
            "--fixture-dir",
            str(tmp_path / "fixtures"),
            "--out",
            str(json_path),
            "--markdown",
            str(markdown_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["generated_fixture"]["logical_bytes"] >= 32768
    assert payload["generated_fixture"]["input_file_count"] == 4
    assert payload["pipeline_counts"]["raw_lines"] == payload["generated_fixture"]["raw_lines"]
    assert payload["pipeline_counts"]["files"] == 5
    assert payload["pipeline_counts"]["templates"] > 0
    assert payload["pipeline_counts"]["representative_samples"] > 0
    assert payload["pipeline_counts"]["annotations"] == payload["annotation_model_call_count"]
    assert payload["summary_model_call_count"] == 1
    assert payload["model_call_count"] == (
        payload["annotation_model_call_count"] + payload["summary_model_call_count"]
    )
    assert payload["pipeline_counts"]["windows"] > 0
    assert payload["pipeline_counts"]["causal_nodes"] > 0
    assert payload["pipeline_counts"]["causal_edges"] > 0
    assert payload["review_load_reduction"] > 0
    assert payload["causal_summary"]["present"] is True
    assert payload["causal_summary"]["next_actions"] > 0
    assert payload["performance"]["wall_time_seconds"] > 0

    json_text = json_path.read_text(encoding="utf-8")
    markdown_text = markdown_path.read_text(encoding="utf-8")
    assert find_unsafe_report_terms(json_text) == []
    assert find_unsafe_report_terms(markdown_text) == []
    for forbidden in (
        "payment-service timeout calling auth-service",
        "Traceback (most recent call last):",
        "Authorization",
        "Bearer",
        "password",
        "token=fixture",
        str(tmp_path),
    ):
        assert forbidden not in json_text
        assert forbidden not in markdown_text
