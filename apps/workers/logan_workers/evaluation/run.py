from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from logan_workers.evaluation.evaluator import evaluate_benchmark_path
from logan_workers.evaluation.reporting import report_to_json, report_to_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline LogAn benchmark evaluation.")
    parser.add_argument(
        "--benchmark",
        required=True,
        help="Path to a benchmark directory containing manifest.json and labels.json.",
    )
    parser.add_argument("--out", required=True, help="Path for the JSON evaluation report.")
    parser.add_argument("--markdown", help="Optional path for the Markdown evaluation summary.")
    return parser


async def _run(args: argparse.Namespace) -> int:
    report = await evaluate_benchmark_path(args.benchmark)
    json_text = report_to_json(report)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json_text + "\n", encoding="utf-8")

    if args.markdown:
        markdown_text = report_to_markdown(report)
        markdown_path = Path(args.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_text, encoding="utf-8")

    return 0 if report.status == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
