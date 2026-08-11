"""Benchmark orchestration over existing RootLens libraries."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx
from rootlens_diagnosis.config import DiagnosisConfig
from rootlens_diagnosis.engine import DiagnosisEngine, collect_telemetry
from rootlens_diagnosis.evaluation import evaluate_existing_diagnosis
from rootlens_diagnosis.incident_context import load_analysis_context, normalized_window
from rootlens_diagnosis.models import DiagnosisReport, EvaluationReport, SourceStatus
from rootlens_diagnosis.reports import (
    write_diagnosis_report,
    write_evaluation_report,
)
from rootlens_scenarios.models import IncidentReport, ScenarioName, ScenarioParameters

from rootlens_benchmark.aggregation import aggregate_report
from rootlens_benchmark.config import BenchmarkConfig
from rootlens_benchmark.models import (
    BenchmarkOutcome,
    IndividualRunSummary,
)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
Progress = Callable[[str], None]
Preflight = Callable[[], Awaitable[None]]


class ScenarioOperations(Protocol):
    async def run(
        self, scenario: ScenarioName, parameters: ScenarioParameters
    ) -> tuple[IncidentReport, Path]: ...

    async def reset(self) -> None: ...


class DiagnosisOperations(Protocol):
    async def diagnose(
        self, incident_path: Path
    ) -> tuple[DiagnosisReport, Path, float]: ...


class EvaluationOperations(Protocol):
    def evaluate(
        self, diagnosis_path: Path, incident_path: Path
    ) -> EvaluationReport: ...


class LibraryDiagnosisOperations:
    """Call diagnosis-engine functions directly with a safe incident projection."""

    def __init__(self, config: DiagnosisConfig, clock: Clock = time.perf_counter):
        self._config = config
        self._clock = clock

    async def diagnose(
        self, incident_path: Path
    ) -> tuple[DiagnosisReport, Path, float]:
        started = self._clock()
        context = load_analysis_context(incident_path)
        window = normalized_window(context, self._config.window_padding_seconds)
        telemetry = await collect_telemetry(self._config, window, context)
        report = DiagnosisEngine().analyze(context, window, telemetry)
        report_path = write_diagnosis_report(report, self._config.prepare_output_dir())
        duration_ms = max(0.0, (self._clock() - started) * 1000)
        return report, report_path, round(duration_ms, 3)


class LibraryEvaluationOperations:
    """Evaluate only a diagnosis that has already been persisted."""

    def __init__(self, output_dir: Path):
        self._output_dir = output_dir

    def evaluate(self, diagnosis_path: Path, incident_path: Path) -> EvaluationReport:
        report = evaluate_existing_diagnosis(diagnosis_path, incident_path)
        write_evaluation_report(report, self._output_dir)
        return report


class BenchmarkRunner:
    """Run scenarios, diagnosis, and isolated evaluation in a fixed sequence."""

    def __init__(
        self,
        config: BenchmarkConfig,
        scenarios: ScenarioOperations,
        diagnoses: DiagnosisOperations,
        evaluations: EvaluationOperations,
        *,
        preflight: Preflight,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.perf_counter,
        progress: Progress = print,
    ) -> None:
        config.validate()
        self._config = config
        self._scenarios = scenarios
        self._diagnoses = diagnoses
        self._evaluations = evaluations
        self._preflight = preflight
        self._sleep = sleep
        self._clock = clock
        self._progress = progress

    async def run(self) -> BenchmarkOutcome:
        benchmark_id = make_benchmark_id()
        runs: list[IndividualRunSummary] = []
        warnings: list[str] = []
        evaluation_failed = False
        reset_failed = False
        preflight_failed = False
        self._progress(f"Starting benchmark {benchmark_id}")
        try:
            try:
                await self._preflight()
                self._progress("Required services are reachable.")
            except Exception:
                preflight_failed = True
                warnings.append(
                    "Required service verification failed; no runs started."
                )
            if preflight_failed:
                runs.extend(
                    IndividualRunSummary(
                        run_number=run_number,
                        scenario_label=scenario.value,
                        safe_failure_reason=(
                            "Run not attempted because service verification failed."
                        ),
                    )
                    for scenario in self._config.scenarios
                    for run_number in range(1, self._config.repetitions + 1)
                )
            else:
                stop_for_safety = False
                for scenario in self._config.scenarios:
                    for run_number in range(1, self._config.repetitions + 1):
                        if stop_for_safety:
                            runs.append(
                                IndividualRunSummary(
                                    run_number=run_number,
                                    scenario_label=scenario.value,
                                    safe_failure_reason=(
                                        "Run not attempted because fault reset failed."
                                    ),
                                )
                            )
                            continue
                        self._progress(
                            f"[{scenario.value} {run_number}/"
                            f"{self._config.repetitions}] generating incident"
                        )
                        summary, run_evaluation_failed = await self._run_once(
                            scenario, run_number
                        )
                        evaluation_failed = evaluation_failed or run_evaluation_failed
                        runs.append(summary)
                        try:
                            await self._scenarios.reset()
                        except Exception:
                            reset_failed = True
                            stop_for_safety = True
                            warnings.append(
                                "Fault reset failed after a run; remaining runs were "
                                "stopped for safety."
                            )
        finally:
            try:
                await self._scenarios.reset()
            except Exception:
                reset_failed = True
                warnings.append("Final fault reset failed; verify Inventory controls.")

        report = aggregate_report(self._config, benchmark_id, runs, warnings)
        passes = benchmark_passes(
            report,
            evaluation_failed=evaluation_failed,
            reset_failed=reset_failed,
            preflight_failed=preflight_failed,
        )
        return BenchmarkOutcome(report=report, exit_code=0 if passes else 1)

    async def _run_once(
        self, scenario: ScenarioName, run_number: int
    ) -> tuple[IndividualRunSummary, bool]:
        parameters = ScenarioParameters(
            requests=self._config.requests,
            concurrency=self._config.concurrency,
            delay_ms=self._config.latency_delay_ms,
        )
        incident: IncidentReport | None = None
        incident_path: Path | None = None
        diagnosis: DiagnosisReport | None = None
        diagnosis_path: Path | None = None
        scenario_started = self._clock()
        try:
            incident, incident_path = await self._scenarios.run(scenario, parameters)
        except Exception:
            return (
                IndividualRunSummary(
                    run_number=run_number,
                    scenario_label=scenario.value,
                    scenario_duration_ms=_elapsed_ms(self._clock, scenario_started),
                    safe_failure_reason="Scenario generation failed.",
                ),
                False,
            )
        scenario_duration = _elapsed_ms(self._clock, scenario_started)
        self._progress(
            f"[{scenario.value} {run_number}/{self._config.repetitions}] "
            "waiting for telemetry"
        )
        await self._sleep(self._config.telemetry_settle_seconds)
        try:
            self._progress(
                f"[{scenario.value} {run_number}/{self._config.repetitions}] "
                "running deterministic diagnosis"
            )
            (
                diagnosis,
                diagnosis_path,
                diagnosis_duration,
            ) = await self._diagnoses.diagnose(incident_path)
        except Exception:
            return (
                IndividualRunSummary(
                    run_number=run_number,
                    scenario_label=scenario.value,
                    incident_report_id=incident.scenario_id,
                    scenario_duration_ms=scenario_duration,
                    safe_failure_reason="Diagnosis failed.",
                ),
                False,
            )

        # This is the first operation allowed to read expected_root_cause. The
        # diagnosis report was atomically written by the preceding operation.
        try:
            evaluation = self._evaluations.evaluate(diagnosis_path, incident_path)
        except Exception:
            return (
                IndividualRunSummary(
                    run_number=run_number,
                    scenario_label=scenario.value,
                    incident_report_id=incident.scenario_id,
                    diagnosis_report_id=diagnosis.diagnosis_id,
                    predicted_root_cause=diagnosis.suspected_root_cause.value,
                    confidence=diagnosis.confidence,
                    confidence_level=diagnosis.confidence_level,
                    telemetry_coverage=diagnosis.telemetry_coverage,
                    diagnosis_duration_ms=diagnosis_duration,
                    scenario_duration_ms=scenario_duration,
                    safe_failure_reason="Evaluation failed.",
                ),
                True,
            )
        self._progress(
            f"[{scenario.value} {run_number}/{self._config.repetitions}] "
            f"{'PASS' if evaluation.exact_match else 'FAIL'}: "
            f"{evaluation.predicted_root_cause.value}"
        )
        return (
            IndividualRunSummary(
                run_number=run_number,
                scenario_label=scenario.value,
                incident_report_id=incident.scenario_id,
                diagnosis_report_id=diagnosis.diagnosis_id,
                predicted_root_cause=evaluation.predicted_root_cause.value,
                expected_root_cause=evaluation.expected_root_cause,
                exact_match=evaluation.exact_match,
                confidence=evaluation.confidence,
                confidence_level=diagnosis.confidence_level,
                telemetry_coverage=evaluation.telemetry_coverage,
                diagnosis_duration_ms=diagnosis_duration,
                scenario_duration_ms=scenario_duration,
            ),
            False,
        )


def benchmark_passes(
    report: object,
    *,
    evaluation_failed: bool,
    reset_failed: bool,
    preflight_failed: bool,
) -> bool:
    from rootlens_benchmark.models import BenchmarkReport

    if not isinstance(report, BenchmarkReport):
        return False
    every_scenario_completed = all(
        result.completed_runs > 0 for result in report.per_scenario_results.values()
    )
    all_sources_unavailable = any(
        run.telemetry_coverage is not None
        and run.telemetry_coverage.available_source_count() == 0
        for run in report.individual_run_summaries
    )
    required_source_missing = report.configuration.require_all_sources and any(
        run.telemetry_coverage is not None
        and any(
            status is SourceStatus.UNAVAILABLE
            for status in (
                run.telemetry_coverage.metrics,
                run.telemetry_coverage.logs,
                run.telemetry_coverage.traces,
            )
        )
        for run in report.individual_run_summaries
    )
    return all(
        (
            every_scenario_completed,
            report.overall_accuracy == 1.0,
            not evaluation_failed,
            not reset_failed,
            not preflight_failed,
            not all_sources_unavailable,
            not required_source_missing,
        )
    )


async def verify_required_services(
    check_business_services: Callable[[], Awaitable[None]],
    config: DiagnosisConfig,
) -> None:
    """Verify business and telemetry endpoints without changing service state."""
    await check_business_services()
    timeout = httpx.Timeout(config.timeout_seconds)
    endpoints = (
        (config.prometheus_url, "/-/ready"),
        (config.loki_url, "/ready"),
        (config.jaeger_url, "/api/services"),
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        for base_url, path in endpoints:
            try:
                response = await client.get(f"{base_url}{path}")
            except httpx.RequestError as error:
                raise RuntimeError(
                    "required telemetry service is unreachable"
                ) from error
            if not 200 <= response.status_code < 300:
                raise RuntimeError("required telemetry service health check failed")


def make_benchmark_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"benchmark-{timestamp}-{uuid4().hex[:8]}"


def _elapsed_ms(clock: Clock, started: float) -> float:
    return round(max(0.0, (clock() - started) * 1000), 3)
