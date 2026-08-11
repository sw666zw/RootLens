"""Safe atomic benchmark JSON and Markdown reports."""

import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from rootlens_benchmark.models import BenchmarkReport


def markdown_summary(report: BenchmarkReport) -> str:
    accuracy = (
        "n/a"
        if report.overall_accuracy is None
        else f"{report.overall_accuracy * 100:.1f}%"
    )
    confidence = (
        "n/a"
        if report.average_confidence is None
        else f"{report.average_confidence:.3f}"
    )
    lines = [
        "# RootLens benchmark summary",
        "",
        "> Benchmark output contains aggregate and bounded report data.",
        "",
        f"- Benchmark ID: `{report.benchmark_id}`",
        f"- Generated at: `{report.generated_at.isoformat().replace('+00:00', 'Z')}`",
        f"- Runs: {report.completed_runs} completed / {report.total_runs} configured",
        f"- Exact matches: {report.exact_matches}",
        f"- Overall accuracy: {accuracy}",
        f"- Average confidence: {confidence}",
        "",
        "## Per-scenario results",
        "",
        "| Scenario | Completed | Failed | Exact | Accuracy |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for scenario, result in report.per_scenario_results.items():
        scenario_accuracy = (
            "n/a" if result.accuracy is None else f"{result.accuracy * 100:.1f}%"
        )
        lines.append(
            f"| {scenario} | {result.completed_runs} | {result.failed_runs} | "
            f"{result.exact_matches} | {scenario_accuracy} |"
        )
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines) + "\n"


def write_reports_atomic(
    report: BenchmarkReport, output_dir: Path
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report.benchmark_id}.json"
    markdown_path = output_dir / f"{report.benchmark_id}.md"
    json_payload = (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    _write_text_atomic(json_path, json_payload)
    _write_text_atomic(markdown_path, markdown_summary(report))
    return json_path, markdown_path


def _write_text_atomic(destination: Path, payload: str) -> None:
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def load_benchmark_report(path: Path) -> BenchmarkReport:
    if not path.is_file():
        raise ValueError("benchmark report path must be an existing file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return BenchmarkReport.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError(
            "benchmark report must be readable valid benchmark JSON"
        ) from error


def printable_summary(report: BenchmarkReport) -> str:
    accuracy = (
        "n/a"
        if report.overall_accuracy is None
        else f"{report.overall_accuracy * 100:.1f}%"
    )
    return (
        f"Benchmark {report.benchmark_id}\n"
        f"Completed: {report.completed_runs}/{report.total_runs}\n"
        f"Exact matches: {report.exact_matches}\n"
        f"Overall accuracy: {accuracy}\n"
        f"Failed runs: {report.failed_runs}"
    )
