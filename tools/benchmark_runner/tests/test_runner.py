"""Offline orchestration, isolation, failure, and exit tests."""

from pathlib import Path

import pytest
from rootlens_diagnosis.models import RootCause, SourceStatus
from rootlens_diagnosis.reports import write_diagnosis_report
from rootlens_scenarios.models import ScenarioName
from tools.benchmark_runner.tests.conftest import (
    FakeDiagnoses,
    FakeEvaluations,
    FakeScenarios,
)

from rootlens_benchmark.config import BenchmarkConfig
from rootlens_benchmark.runner import BenchmarkRunner


async def no_preflight() -> None:
    return None


def config(*, scenarios=(ScenarioName.BASELINE,), repetitions=1) -> BenchmarkConfig:
    return BenchmarkConfig(
        scenarios=scenarios,
        repetitions=repetitions,
        requests=1,
        concurrency=1,
        latency_delay_ms=1500,
        telemetry_settle_seconds=7,
    )


@pytest.mark.asyncio
async def test_scenarios_run_in_sequence_with_repetitions(tmp_path: Path) -> None:
    events: list[str] = []
    scenarios = FakeScenarios(tmp_path, events)
    diagnoses = FakeDiagnoses(
        tmp_path / "diagnoses",
        events,
        [
            RootCause.NONE,
            RootCause.NONE,
            RootCause.INVENTORY_SERVICE_UNAVAILABLE,
            RootCause.INVENTORY_SERVICE_UNAVAILABLE,
        ],
    )
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    runner = BenchmarkRunner(
        config(
            scenarios=(ScenarioName.BASELINE, ScenarioName.INVENTORY_UNAVAILABLE),
            repetitions=2,
        ),
        scenarios,
        diagnoses,
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=sleep,
        progress=lambda _: None,
    )
    outcome = await runner.run()
    assert scenarios.calls == [
        ScenarioName.BASELINE,
        ScenarioName.BASELINE,
        ScenarioName.INVENTORY_UNAVAILABLE,
        ScenarioName.INVENTORY_UNAVAILABLE,
    ]
    assert sleeps == [7, 7, 7, 7]
    assert outcome.report.total_runs == 4
    assert outcome.report.completed_runs == 4
    assert outcome.exit_code == 0


@pytest.mark.asyncio
async def test_diagnosis_is_written_before_ground_truth_evaluation(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    scenarios = FakeScenarios(tmp_path, events)
    diagnoses = FakeDiagnoses(tmp_path / "diagnoses", events, [RootCause.NONE])
    outcome = await BenchmarkRunner(
        config(),
        scenarios,
        diagnoses,
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    assert events.index("diagnosis-written:1") < events.index("evaluate:1")
    forbidden = {"scenario_name", "expected_root_cause", "expected_symptoms"}
    assert diagnoses.context_keys
    assert diagnoses.context_keys[0].isdisjoint(forbidden)
    assert outcome.report.individual_run_summaries[0].exact_match is True


@pytest.mark.asyncio
async def test_openai_is_never_imported_or_called(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []

    def forbidden_import(name: str, *args, **kwargs):
        if name == "openai":
            raise AssertionError("benchmark must never import OpenAI")
        return original_import(name, *args, **kwargs)

    import importlib

    original_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", forbidden_import)
    outcome = await BenchmarkRunner(
        config(),
        FakeScenarios(tmp_path, events),
        FakeDiagnoses(tmp_path / "diagnoses", events, [RootCause.NONE]),
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    assert outcome.exit_code == 0


@pytest.mark.asyncio
async def test_fault_reset_occurs_after_success_and_in_finally(tmp_path: Path) -> None:
    events: list[str] = []
    scenarios = FakeScenarios(tmp_path, events)
    await BenchmarkRunner(
        config(),
        scenarios,
        FakeDiagnoses(tmp_path / "diagnoses", events, [RootCause.NONE]),
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    assert scenarios.reset_calls == 2
    assert events[-1] == "reset"


@pytest.mark.asyncio
async def test_failure_is_safe_and_reset_then_next_run_occurs(tmp_path: Path) -> None:
    events: list[str] = []
    scenarios = FakeScenarios(tmp_path, events, fail_calls={1})
    outcome = await BenchmarkRunner(
        config(repetitions=2),
        scenarios,
        FakeDiagnoses(tmp_path / "diagnoses", events, [RootCause.NONE]),
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    assert scenarios.reset_calls == 3
    assert len(scenarios.calls) == 2
    failed = outcome.report.individual_run_summaries[0]
    assert failed.safe_failure_reason == "Scenario generation failed."
    assert "private" not in failed.model_dump_json()
    assert outcome.exit_code == 0


@pytest.mark.asyncio
async def test_missing_diagnosis_is_recorded_safely_and_nonzero_without_completion(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    outcome = await BenchmarkRunner(
        config(),
        FakeScenarios(tmp_path, events),
        FakeDiagnoses(tmp_path / "diagnoses", events, [RootCause.NONE], {1}),
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    run = outcome.report.individual_run_summaries[0]
    assert run.diagnosis_report_id is None
    assert run.safe_failure_reason == "Diagnosis failed."
    assert outcome.exit_code == 1


@pytest.mark.asyncio
async def test_mismatched_diagnosis_exits_nonzero(tmp_path: Path) -> None:
    events: list[str] = []
    outcome = await BenchmarkRunner(
        config(),
        FakeScenarios(tmp_path, events),
        FakeDiagnoses(
            tmp_path / "diagnoses",
            events,
            [RootCause.INVENTORY_SERVICE_UNAVAILABLE],
        ),
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    assert outcome.report.overall_accuracy == 0.0
    assert outcome.exit_code == 1


@pytest.mark.asyncio
async def test_evaluation_failure_is_nonzero(tmp_path: Path) -> None:
    events: list[str] = []
    outcome = await BenchmarkRunner(
        config(),
        FakeScenarios(tmp_path, events),
        FakeDiagnoses(tmp_path / "diagnoses", events, [RootCause.NONE]),
        FakeEvaluations(events, fail=True),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    assert outcome.report.individual_run_summaries[0].safe_failure_reason == (
        "Evaluation failed."
    )
    assert outcome.exit_code == 1


@pytest.mark.asyncio
async def test_all_telemetry_unavailable_exits_nonzero(tmp_path: Path) -> None:
    events: list[str] = []

    class UnavailableDiagnoses(FakeDiagnoses):
        async def diagnose(self, incident_path: Path):
            report, path, duration = await super().diagnose(incident_path)
            unavailable = report.telemetry_coverage.model_copy(
                update={
                    "metrics": SourceStatus.UNAVAILABLE,
                    "logs": SourceStatus.UNAVAILABLE,
                    "traces": SourceStatus.UNAVAILABLE,
                }
            )
            updated = report.model_copy(update={"telemetry_coverage": unavailable})
            write_diagnosis_report(updated, path.parent)
            return updated, path, duration

    outcome = await BenchmarkRunner(
        config(),
        FakeScenarios(tmp_path, events),
        UnavailableDiagnoses(tmp_path / "diagnoses", events, [RootCause.NONE]),
        FakeEvaluations(events),
        preflight=no_preflight,
        sleep=_no_sleep,
        progress=lambda _: None,
    ).run()
    assert outcome.report.overall_accuracy == 1.0
    assert outcome.exit_code == 1


async def _no_sleep(_: float) -> None:
    return None
