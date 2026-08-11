"""Typed benchmark result models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from rootlens_diagnosis.models import TelemetryCoverage


class BenchmarkConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenarios: list[str]
    repetitions: int
    requests: int
    concurrency: int
    latency_delay_ms: int
    telemetry_settle_seconds: int
    require_all_sources: bool


class DurationStatistics(BaseModel):
    count: int = 0
    minimum_ms: float | None = None
    maximum_ms: float | None = None
    average_ms: float | None = None
    median_ms: float | None = None


class IndividualRunSummary(BaseModel):
    run_number: int
    scenario_label: str
    incident_report_id: str | None = None
    diagnosis_report_id: str | None = None
    predicted_root_cause: str | None = None
    expected_root_cause: str | None = None
    exact_match: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_level: str | None = None
    telemetry_coverage: TelemetryCoverage | None = None
    diagnosis_duration_ms: float | None = Field(default=None, ge=0)
    scenario_duration_ms: float | None = Field(default=None, ge=0)
    safe_failure_reason: str | None = None


class ScenarioResult(BaseModel):
    configured_runs: int
    completed_runs: int
    failed_runs: int
    exact_matches: int
    accuracy: float | None = Field(default=None, ge=0, le=1)


class BenchmarkReport(BaseModel):
    schema_version: str = "1.0"
    benchmark_id: str
    generated_at: datetime
    configuration: BenchmarkConfiguration
    total_runs: int
    completed_runs: int
    failed_runs: int
    exact_matches: int
    overall_accuracy: float | None = Field(default=None, ge=0, le=1)
    per_scenario_results: dict[str, ScenarioResult]
    confusion_matrix: dict[str, dict[str, int]]
    average_confidence: float | None = Field(default=None, ge=0, le=1)
    average_confidence_by_scenario: dict[str, float | None]
    confidence_level_counts: dict[str, int]
    telemetry_coverage_counts: dict[str, dict[str, int]]
    diagnosis_duration_statistics: DurationStatistics
    scenario_duration_statistics: DurationStatistics
    individual_run_summaries: list[IndividualRunSummary]
    warnings: list[str]


class BenchmarkOutcome(BaseModel):
    report: BenchmarkReport
    exit_code: int
