"""Deterministic aggregation of individual benchmark runs."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import fmean, median

from rootlens_benchmark.config import BenchmarkConfig
from rootlens_benchmark.models import (
    BenchmarkConfiguration,
    BenchmarkReport,
    DurationStatistics,
    IndividualRunSummary,
    ScenarioResult,
)


def duration_statistics(values: list[float]) -> DurationStatistics:
    if not values:
        return DurationStatistics()
    return DurationStatistics(
        count=len(values),
        minimum_ms=round(min(values), 3),
        maximum_ms=round(max(values), 3),
        average_ms=round(fmean(values), 3),
        median_ms=round(median(values), 3),
    )


def aggregate_report(
    config: BenchmarkConfig,
    benchmark_id: str,
    runs: list[IndividualRunSummary],
    warnings: list[str],
    *,
    generated_at: datetime | None = None,
) -> BenchmarkReport:
    completed = [run for run in runs if run.exact_match is not None]
    exact_matches = sum(run.exact_match is True for run in completed)
    per_scenario: dict[str, ScenarioResult] = {}
    confidence_by_scenario: dict[str, float | None] = {}
    for scenario in config.scenarios:
        label = scenario.value
        selected = [run for run in runs if run.scenario_label == label]
        selected_completed = [run for run in selected if run.exact_match is not None]
        selected_exact = sum(run.exact_match is True for run in selected_completed)
        confidences = [
            run.confidence for run in selected_completed if run.confidence is not None
        ]
        per_scenario[label] = ScenarioResult(
            configured_runs=config.repetitions,
            completed_runs=len(selected_completed),
            failed_runs=config.repetitions - len(selected_completed),
            exact_matches=selected_exact,
            accuracy=(
                round(selected_exact / len(selected_completed), 6)
                if selected_completed
                else None
            ),
        )
        confidence_by_scenario[label] = (
            round(fmean(confidences), 6) if confidences else None
        )

    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for run in completed:
        if run.expected_root_cause and run.predicted_root_cause:
            matrix[run.expected_root_cause][run.predicted_root_cause] += 1

    levels = Counter(
        run.confidence_level for run in completed if run.confidence_level is not None
    )
    coverage = {
        source: Counter(
            getattr(run.telemetry_coverage, source).value
            for run in completed
            if run.telemetry_coverage is not None
        )
        for source in ("metrics", "logs", "traces")
    }
    confidences = [run.confidence for run in completed if run.confidence is not None]
    return BenchmarkReport(
        benchmark_id=benchmark_id,
        generated_at=(generated_at or datetime.now(UTC)).astimezone(UTC),
        configuration=BenchmarkConfiguration(
            scenarios=[item.value for item in config.scenarios],
            repetitions=config.repetitions,
            requests=config.requests,
            concurrency=config.concurrency,
            latency_delay_ms=config.latency_delay_ms,
            telemetry_settle_seconds=config.telemetry_settle_seconds,
            require_all_sources=config.require_all_sources,
        ),
        total_runs=len(config.scenarios) * config.repetitions,
        completed_runs=len(completed),
        failed_runs=len(config.scenarios) * config.repetitions - len(completed),
        exact_matches=exact_matches,
        overall_accuracy=(
            round(exact_matches / len(completed), 6) if completed else None
        ),
        per_scenario_results=per_scenario,
        confusion_matrix={
            expected: dict(sorted(predictions.items()))
            for expected, predictions in sorted(matrix.items())
        },
        average_confidence=round(fmean(confidences), 6) if confidences else None,
        average_confidence_by_scenario=confidence_by_scenario,
        confidence_level_counts=dict(sorted(levels.items())),
        telemetry_coverage_counts={
            source: dict(sorted(counts.items())) for source, counts in coverage.items()
        },
        diagnosis_duration_statistics=duration_statistics(
            [
                run.diagnosis_duration_ms
                for run in completed
                if run.diagnosis_duration_ms is not None
            ]
        ),
        scenario_duration_statistics=duration_statistics(
            [
                run.scenario_duration_ms
                for run in runs
                if run.scenario_duration_ms is not None
            ]
        ),
        individual_run_summaries=runs,
        warnings=list(dict.fromkeys(warnings)),
    )
