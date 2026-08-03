"""Command-line entry point for RootLens local incident scenarios."""

import argparse
import asyncio
import os
from pathlib import Path

import httpx

from rootlens_scenarios.client import ScenarioClient
from rootlens_scenarios.models import ScenarioName, ScenarioParameters
from rootlens_scenarios.runner import ScenarioRunner, ScenarioValidationError


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def delay_integer(value: str) -> int:
    parsed = positive_integer(value)
    if parsed > 10_000:
        raise argparse.ArgumentTypeError("must not exceed 10000")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rootlens-scenario")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a controlled incident scenario")
    scenarios = run.add_subparsers(dest="scenario", required=True)
    for scenario in ScenarioName:
        scenario_parser = scenarios.add_parser(scenario.value)
        scenario_parser.add_argument("--requests", type=positive_integer, default=20)
        scenario_parser.add_argument("--concurrency", type=positive_integer, default=5)
        scenario_parser.add_argument("--output-dir", type=Path)
        if scenario is ScenarioName.INVENTORY_LATENCY:
            scenario_parser.add_argument("--delay-ms", type=delay_integer, default=1500)
    commands.add_parser("reset", help="clear Inventory reservation faults")
    return parser


async def run_command(args: argparse.Namespace) -> int:
    inventory_url = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8000")
    order_url = os.getenv("ORDER_SERVICE_URL", "http://localhost:8001")
    output_dir = getattr(args, "output_dir", None) or Path(
        os.getenv("ROOTLENS_INCIDENT_OUTPUT_DIR", "runtime/incidents")
    )
    async with ScenarioClient.create(inventory_url, order_url) as client:
        runner = ScenarioRunner(client, output_dir)
        if args.command == "reset":
            await runner.reset()
            print("Inventory reservation faults reset.")
            return 0
        scenario = ScenarioName(args.scenario)
        parameters = ScenarioParameters(
            requests=args.requests,
            concurrency=args.concurrency,
            delay_ms=getattr(args, "delay_ms", 1500),
        )
        try:
            report, path = await runner.run(scenario, parameters)
        except ScenarioValidationError as error:
            print(f"Scenario outcome mismatch: {error}")
            return 1
        print(
            f"Scenario {report.scenario_name}: "
            f"{report.successful_requests} successful, "
            f"{report.failed_requests} failed; "
            f"average {report.average_duration_ms:.3f} ms"
        )
        print(f"Ground truth: {path}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run" and args.concurrency > args.requests:
        parser.error("--concurrency may not exceed --requests")
    try:
        return asyncio.run(run_command(args))
    except (httpx.RequestError, OSError, RuntimeError, ValueError) as error:
        print(f"Scenario failed: {error}")
        return 1
