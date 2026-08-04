"""Command-line entry point for deterministic RootLens diagnosis."""

import argparse
import asyncio
import os
from pathlib import Path

from rootlens_diagnosis.config import (
    DEFAULT_OUTPUT_DIR,
    DiagnosisConfig,
    prepare_output_directory,
)
from rootlens_diagnosis.engine import DiagnosisEngine, collect_telemetry
from rootlens_diagnosis.evaluation import evaluate_existing_diagnosis
from rootlens_diagnosis.incident_context import load_analysis_context, normalized_window
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.reports import write_diagnosis_report, write_evaluation_report


def non_negative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rootlens-diagnose")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="correlate telemetry for an incident")
    analyze.add_argument("incident_report", type=Path)
    analyze.add_argument("--output-dir", type=Path)
    analyze.add_argument("--prometheus-url")
    analyze.add_argument("--loki-url")
    analyze.add_argument("--jaeger-url")
    analyze.add_argument("--window-padding-seconds", type=non_negative_integer)
    analyze.add_argument("--require-all-sources", action="store_true")
    evaluate = commands.add_parser("evaluate", help="compare a completed diagnosis")
    evaluate.add_argument("diagnosis_report", type=Path)
    evaluate.add_argument("incident_report", type=Path)
    evaluate.add_argument("--output-dir", type=Path)
    return parser


async def run_analyze(args: argparse.Namespace) -> int:
    context = load_analysis_context(args.incident_report)
    config = DiagnosisConfig.from_environment(
        prometheus_url=args.prometheus_url,
        loki_url=args.loki_url,
        jaeger_url=args.jaeger_url,
        output_dir=args.output_dir,
        window_padding_seconds=args.window_padding_seconds,
        require_all_sources=args.require_all_sources,
    )
    output_dir = config.prepare_output_dir()
    window = normalized_window(context, config.window_padding_seconds)
    telemetry = await collect_telemetry(config, window, context)
    report = DiagnosisEngine().analyze(context, window, telemetry)
    report_path = write_diagnosis_report(report, output_dir)
    source_statuses = {
        "metrics": report.telemetry_coverage.metrics,
        "logs": report.telemetry_coverage.logs,
        "traces": report.telemetry_coverage.traces,
    }
    sources = (
        ", ".join(
            name
            for name, status in source_statuses.items()
            if status is not SourceStatus.UNAVAILABLE
        )
        or "none"
    )
    print(f"Diagnosis: {report.suspected_root_cause.value}")
    print(f"Affected service: {report.affected_service or 'none'}")
    print(f"Confidence: {report.confidence:.3f} ({report.confidence_level})")
    print(f"Evidence sources: {sources}")
    print(f"Report: {report_path}")
    all_unavailable = report.telemetry_coverage.available_source_count() == 0
    missing_required = config.require_all_sources and any(
        status is SourceStatus.UNAVAILABLE for status in source_statuses.values()
    )
    return 1 if all_unavailable or missing_required else 0


def run_evaluate(args: argparse.Namespace) -> int:
    output_dir = args.output_dir or Path(
        os.getenv("ROOTLENS_DIAGNOSIS_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))
    )
    prepared = prepare_output_directory(output_dir)
    report = evaluate_existing_diagnosis(args.diagnosis_report, args.incident_report)
    report_path = write_evaluation_report(report, prepared)
    print("PASS" if report.exact_match else "FAIL")
    print(f"Predicted root cause: {report.predicted_root_cause.value}")
    print(f"Expected root cause: {report.expected_root_cause}")
    print(f"Diagnosis report: {args.diagnosis_report}")
    print(f"Evaluation report: {report_path}")
    return 0 if report.exact_match else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return asyncio.run(run_analyze(args))
        return run_evaluate(args)
    except (OSError, ValueError) as error:
        print(f"Diagnosis command failed: {error}")
        return 2
