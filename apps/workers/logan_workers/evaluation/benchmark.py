from __future__ import annotations

import json
from pathlib import Path

from logan_workers.evaluation.schemas import BenchmarkLabels, BenchmarkManifest, LoadedBenchmark


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_benchmark(benchmark_dir: str | Path) -> LoadedBenchmark:
    base = Path(benchmark_dir)
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"benchmark manifest not found: {manifest_path}")

    manifest = BenchmarkManifest.model_validate(_load_json(manifest_path))
    labels_path = base / manifest.labels_path
    if not labels_path.exists():
        raise FileNotFoundError(f"benchmark labels not found: {labels_path}")
    labels = BenchmarkLabels.model_validate(_load_json(labels_path))

    input_paths = [(base / raw_path).resolve() for raw_path in manifest.input_paths]
    missing = [path for path in input_paths if not path.exists()]
    if missing:
        missing_names = ", ".join(path.name for path in missing)
        raise FileNotFoundError(f"benchmark input file(s) not found: {missing_names}")

    return LoadedBenchmark(
        benchmark_dir=base.resolve(),
        manifest=manifest,
        labels=labels,
        input_paths=input_paths,
    )
