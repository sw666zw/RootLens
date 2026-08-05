"""Command-line entry point for deterministic RootLens diagnosis."""

import argparse
import asyncio
import os
from pathlib import Path

from rootlens_diagnosis.config import (
    DEFAULT_EXPLANATION_OUTPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    DiagnosisConfig,
    ExplanationConfig,
    prepare_output_directory,
)
from rootlens_diagnosis.engine import DiagnosisEngine, collect_telemetry
from rootlens_diagnosis.evaluation import evaluate_existing_diagnosis, load_diagnosis
from rootlens_diagnosis.explanation_models import ProviderStatus
from rootlens_diagnosis.explanation_projection import build_safe_explanation_input
from rootlens_diagnosis.explanation_providers import (
    ExplanationProvider,
    ExplanationProviderError,
    TemplateExplanationProvider,
    configured_provider,
)
from rootlens_diagnosis.explanation_validation import validate_explanation_file
from rootlens_diagnosis.explanations import (
    create_explanation_report,
    generate_with_provider,
)
from rootlens_diagnosis.incident_context import load_analysis_context, normalized_window
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.reports import (
    write_diagnosis_report,
    write_evaluation_report,
    write_explanation_report,
    write_explanation_validation_report,
)


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
    explain = commands.add_parser(
        "explain", help="explain an existing deterministic diagnosis"
    )
    explain.add_argument("diagnosis_report", type=Path)
    explain.add_argument("--output-dir", type=Path)
    explain.add_argument("--allow-template-fallback", action="store_true")
    validate = commands.add_parser(
        "validate-explanation", help="validate an explanation offline"
    )
    validate.add_argument("explanation_report", type=Path)
    validate.add_argument("diagnosis_report", type=Path)
    validate.add_argument("--output-dir", type=Path)
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


def run_explain(
    args: argparse.Namespace,
    *,
    provider: ExplanationProvider | None = None,
) -> int:
    """Explain a stored diagnosis without telemetry or ground-truth access."""
    config = ExplanationConfig.from_environment(output_dir=args.output_dir)
    diagnosis = load_diagnosis(args.diagnosis_report)
    projection = build_safe_explanation_input(diagnosis)
    selected = provider or configured_provider(config)
    status = ProviderStatus.COMPLETED
    extra_warnings: list[str] = []
    try:
        result = generate_with_provider(selected, projection)
    except ExplanationProviderError as error:
        if config.provider != "openai" or not args.allow_template_fallback:
            raise
        print(f"OpenAI diagnostic: {error}")
        result = TemplateExplanationProvider().generate(projection)
        status = ProviderStatus.FALLBACK
        extra_warnings.append(
            "OpenAI explanation was unavailable; explicit template fallback was used."
        )
    report = create_explanation_report(
        diagnosis,
        projection,
        result,
        provider_status=status,
        extra_warnings=extra_warnings,
    )
    output_dir = config.prepare_output_dir()
    report_path = write_explanation_report(report, output_dir)
    print(report.headline)
    print(report.executive_summary)
    print(f"Provider: {report.provider} ({report.provider_status.value})")
    print(f"Report: {report_path}")
    return 0


def run_validate_explanation(args: argparse.Namespace) -> int:
    output_dir = args.output_dir or Path(
        os.getenv(
            "ROOTLENS_EXPLANATION_OUTPUT_DIR",
            str(DEFAULT_EXPLANATION_OUTPUT_DIR),
        )
    )
    report = validate_explanation_file(args.explanation_report, args.diagnosis_report)
    prepared = prepare_output_directory(output_dir)
    report_path = write_explanation_validation_report(report, prepared)
    print("PASS" if report.overall_valid else "FAIL")
    print(f"Explanation report: {args.explanation_report}")
    print(f"Diagnosis report: {args.diagnosis_report}")
    print(f"Validation report: {report_path}")
    return 0 if report.overall_valid else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return asyncio.run(run_analyze(args))
        if args.command == "evaluate":
            return run_evaluate(args)
        if args.command == "explain":
            return run_explain(args)
        return run_validate_explanation(args)
    except (OSError, ValueError, ExplanationProviderError) as error:
        print(f"Diagnosis command failed: {error}")
        return 2
