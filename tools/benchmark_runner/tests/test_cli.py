"""CLI validation and offline summary tests."""

import json
from datetime import UTC, datetime

import pytest
from rootlens_scenarios.models import ScenarioName

from rootlens_benchmark.cli import build_parser, main, scenario_list
from rootlens_benchmark.models import (
    BenchmarkConfiguration,
    BenchmarkReport,
    DurationStatistics,
)


def test_default_scenario_selection() -> None:
    args = build_parser().parse_args(["run"])
    assert args.scenarios == tuple(ScenarioName)
    assert (args.repetitions, args.requests, args.concurrency) == (3, 10, 5)


def test_scenario_selection_preserves_requested_order() -> None:
    assert scenario_list("inventory-unavailable,baseline") == (
        ScenarioName.INVENTORY_UNAVAILABLE,
        ScenarioName.BASELINE,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "--repetitions", "0"],
        ["run", "--requests", "-1"],
        ["run", "--concurrency", "0"],
        ["run", "--latency-delay-ms", "10001"],
        ["run", "--telemetry-settle-seconds", "-1"],
        ["run", "--scenarios", "baseline,baseline"],
        ["run", "--scenarios", "future-incident"],
    ],
)
def test_argument_validation(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(arguments)


def test_concurrency_may_not_exceed_requests() -> None:
    with pytest.raises(SystemExit):
        main(["run", "--requests", "2", "--concurrency", "3"])


def test_summarize_is_offline_and_does_not_modify_report(
    tmp_path, monkeypatch, capsys
) -> None:
    report = BenchmarkReport(
        benchmark_id="benchmark-example",
        generated_at=datetime(2026, 8, 11, tzinfo=UTC),
        configuration=BenchmarkConfiguration(
            scenarios=["baseline"],
            repetitions=1,
            requests=1,
            concurrency=1,
            latency_delay_ms=1500,
            telemetry_settle_seconds=0,
            require_all_sources=False,
        ),
        total_runs=1,
        completed_runs=1,
        failed_runs=0,
        exact_matches=1,
        overall_accuracy=1.0,
        per_scenario_results={},
        confusion_matrix={"none": {"none": 1}},
        average_confidence=0.75,
        average_confidence_by_scenario={"baseline": 0.75},
        confidence_level_counts={"medium": 1},
        telemetry_coverage_counts={},
        diagnosis_duration_statistics=DurationStatistics(),
        scenario_duration_statistics=DurationStatistics(),
        individual_run_summaries=[],
        warnings=[],
    )
    path = tmp_path / "report.json"
    original = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    path.write_text(original, encoding="utf-8")

    def network_forbidden(*args, **kwargs):
        raise AssertionError("summarize must not construct a network client")

    monkeypatch.setattr("httpx.AsyncClient", network_forbidden)
    assert main(["summarize", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == original
    assert "Overall accuracy: 100.0%" in capsys.readouterr().out
