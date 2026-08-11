"""Command-line interface for live and offline RootLens benchmarks."""

import argparse
import asyncio
import os
from pathlib import Path

from rootlens_diagnosis.config import DEFAULT_OUTPUT_DIR
from rootlens_scenarios.client import ScenarioClient
from rootlens_scenarios.models import ScenarioName
from rootlens_scenarios.runner import ScenarioRunner

from rootlens_benchmark.config import DEFAULT_SCENARIOS, BenchmarkConfig
from rootlens_benchmark.reports import (
    load_benchmark_report,
    printable_summary,
    write_reports_atomic,
)
from rootlens_benchmark.runner import (
    BenchmarkRunner,
    LibraryDiagnosisOperations,
    LibraryEvaluationOperations,
    verify_required_services,
)


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def non_negative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def latency_integer(value: str) -> int:
    parsed = positive_integer(value)
    if parsed > 10_000:
        raise argparse.ArgumentTypeError("must not exceed 10000")
    return parsed


def scenario_list(value: str) -> tuple[ScenarioName, ...]:
    raw = [item.strip() for item in value.split(",")]
    if not raw or any(not item for item in raw):
        raise argparse.ArgumentTypeError("must be a comma-separated scenario list")
    try:
        scenarios = tuple(ScenarioName(item) for item in raw)
    except ValueError as error:
        supported = ", ".join(item.value for item in ScenarioName)
        raise argparse.ArgumentTypeError(
            f"contains an unsupported scenario; choose from {supported}"
        ) from error
    if len(set(scenarios)) != len(scenarios):
        raise argparse.ArgumentTypeError("must not contain duplicate scenarios")
    return scenarios


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rootlens-benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the live deterministic benchmark")
    run.add_argument(
        "--scenarios",
        type=scenario_list,
        default=DEFAULT_SCENARIOS,
    )
    run.add_argument("--repetitions", type=positive_integer, default=3)
    run.add_argument("--requests", type=positive_integer, default=10)
    run.add_argument("--concurrency", type=positive_integer, default=5)
    run.add_argument("--latency-delay-ms", type=latency_integer, default=1500)
    run.add_argument(
        "--telemetry-settle-seconds", type=non_negative_integer, default=15
    )
    run.add_argument("--output-dir", type=Path)
    run.add_argument("--require-all-sources", action="store_true")
    summarize = commands.add_parser(
        "summarize", help="print an existing benchmark report offline"
    )
    summarize.add_argument("benchmark_report_path", type=Path)
    return parser


async def run_command(args: argparse.Namespace) -> int:
    config = BenchmarkConfig.from_values(
        scenarios=args.scenarios,
        repetitions=args.repetitions,
        requests=args.requests,
        concurrency=args.concurrency,
        latency_delay_ms=args.latency_delay_ms,
        telemetry_settle_seconds=args.telemetry_settle_seconds,
        output_dir=args.output_dir,
        require_all_sources=args.require_all_sources,
    )
    diagnosis_config = config.diagnosis_config()
    inventory_url = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8000")
    order_url = os.getenv("ORDER_SERVICE_URL", "http://localhost:8001")
    async with ScenarioClient.create(inventory_url, order_url) as client:
        scenario_runner = ScenarioRunner(client, config.incident_output_dir)

        async def preflight() -> None:
            await verify_required_services(client.check_health, diagnosis_config)

        runner = BenchmarkRunner(
            config,
            scenario_runner,
            LibraryDiagnosisOperations(diagnosis_config),
            LibraryEvaluationOperations(
                Path(
                    os.getenv("ROOTLENS_DIAGNOSIS_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))
                )
            ),
            preflight=preflight,
        )
        outcome = await runner.run()
    try:
        json_path, markdown_path = write_reports_atomic(
            outcome.report, config.output_dir
        )
    except OSError:
        print("Benchmark report could not be written.")
        return 1
    print(printable_summary(outcome.report))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return outcome.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "summarize":
        try:
            print(printable_summary(load_benchmark_report(args.benchmark_report_path)))
        except ValueError as error:
            print(f"Benchmark summary failed: {error}")
            return 2
        return 0
    if args.concurrency > args.requests:
        parser.error("--concurrency may not exceed --requests")
    try:
        return asyncio.run(run_command(args))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Benchmark failed: {error}")
        return 2
