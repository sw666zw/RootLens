"""Aggregate math and safe report persistence tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

from rootlens_diagnosis.models import SourceStatus, TelemetryCoverage
from rootlens_scenarios.models import ScenarioName

from rootlens_benchmark.aggregation import aggregate_report
from rootlens_benchmark.config import BenchmarkConfig
from rootlens_benchmark.models import IndividualRunSummary
from rootlens_benchmark.reports import markdown_summary, write_reports_atomic


def completed(
    number: int,
    expected: str,
    predicted: str,
    confidence: float,
    level: str,
) -> IndividualRunSummary:
    return IndividualRunSummary(
        run_number=number,
        scenario_label="baseline",
        incident_report_id=f"incident-{number}",
        diagnosis_report_id=f"diagnosis-{number}",
        predicted_root_cause=predicted,
        expected_root_cause=expected,
        exact_match=predicted == expected,
        confidence=confidence,
        confidence_level=level,
        telemetry_coverage=TelemetryCoverage(
            metrics=SourceStatus.AVAILABLE,
            logs=SourceStatus.PARTIAL,
            traces=SourceStatus.UNAVAILABLE,
        ),
        diagnosis_duration_ms=float(number * 10),
        scenario_duration_ms=float(number * 20),
    )


def test_aggregate_accuracy_confusion_and_confidence() -> None:
    config = BenchmarkConfig(
        scenarios=(ScenarioName.BASELINE,), repetitions=2, requests=1, concurrency=1
    )
    report = aggregate_report(
        config,
        "benchmark-example",
        [
            completed(1, "none", "none", 0.6, "medium"),
            completed(2, "none", "unknown", 0.2, "low"),
        ],
        [],
        generated_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    assert report.overall_accuracy == 0.5
    assert report.confusion_matrix == {"none": {"none": 1, "unknown": 1}}
    assert report.average_confidence == 0.4
    assert report.average_confidence_by_scenario == {"baseline": 0.4}
    assert report.confidence_level_counts == {"low": 1, "medium": 1}
    assert report.telemetry_coverage_counts["logs"] == {"partial": 2}
    assert report.diagnosis_duration_statistics.average_ms == 15.0
    assert report.scenario_duration_statistics.median_ms == 30.0


def test_required_fields_atomic_reports_and_markdown_json_agree(tmp_path: Path) -> None:
    config = BenchmarkConfig(
        scenarios=(ScenarioName.BASELINE,), repetitions=1, requests=1, concurrency=1
    )
    report = aggregate_report(
        config,
        "benchmark-example",
        [completed(1, "none", "none", 0.6, "medium")],
        [],
        generated_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    json_path, markdown_path = write_reports_atomic(report, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "benchmark_id",
        "generated_at",
        "configuration",
        "total_runs",
        "completed_runs",
        "failed_runs",
        "exact_matches",
        "overall_accuracy",
        "per_scenario_results",
        "confusion_matrix",
        "average_confidence",
        "average_confidence_by_scenario",
        "confidence_level_counts",
        "telemetry_coverage_counts",
        "diagnosis_duration_statistics",
        "scenario_duration_statistics",
        "individual_run_summaries",
        "warnings",
    }
    assert required <= payload.keys()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Runs: 1 completed / 1 configured" in markdown
    assert "Overall accuracy: 100.0%" in markdown
    assert markdown == markdown_summary(report)
    assert not list(tmp_path.glob("*.tmp"))


def test_generated_reports_contain_no_secrets_or_absolute_paths(tmp_path: Path) -> None:
    config = BenchmarkConfig(
        scenarios=(ScenarioName.BASELINE,), repetitions=1, requests=1, concurrency=1
    )
    report = aggregate_report(
        config,
        "benchmark-safe",
        [completed(1, "none", "none", 0.6, "medium")],
        [],
        generated_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    paths = write_reports_atomic(report, tmp_path)
    content = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "OPENAI_API_KEY" not in content
    assert "database_url" not in content.lower()
    assert "idempotency" not in content.lower()
    assert str(tmp_path) not in content
    assert not any(
        value.startswith("/") for value in _strings(json.loads(paths[0].read_text()))
    )


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
