"""Offline benchmark fixtures."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rootlens_diagnosis.evaluation import evaluate_existing_diagnosis
from rootlens_diagnosis.incident_context import AnalysisWindow, load_analysis_context
from rootlens_diagnosis.models import (
    CandidateScore,
    DiagnosisReport,
    InputContextSummary,
    RootCause,
    SourceStatus,
    TelemetryCoverage,
)
from rootlens_diagnosis.reports import write_diagnosis_report
from rootlens_scenarios.models import IncidentReport, ScenarioName


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "template")
    monkeypatch.setenv("ROOTLENS_LLM_ENABLED", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def incident_report(scenario: ScenarioName, number: int) -> IncidentReport:
    causes = {
        ScenarioName.BASELINE: "none",
        ScenarioName.INVENTORY_LATENCY: "inventory_reservation_latency",
        ScenarioName.INVENTORY_UNAVAILABLE: "inventory_service_unavailable",
    }
    return IncidentReport(
        schema_version="1.0",
        scenario_id=f"synthetic-incident-{number}",
        scenario_name=scenario.value,
        started_at="2026-08-11T12:00:00.000Z",
        ended_at="2026-08-11T12:00:01.000Z",
        target_service="inventory",
        parameters={"requests": 1, "concurrency": 1},
        expected_root_cause=causes[scenario],
        expected_symptoms=["synthetic example"],
        inventory_sku="EXAMPLE-SKU",
        total_requests=1,
        concurrency=1,
        response_status_counts={"201": 1},
        successful_requests=1,
        failed_requests=0,
        minimum_duration_ms=1.0,
        maximum_duration_ms=1.0,
        average_duration_ms=1.0,
        request_ids=[f"request-{number}"],
        trace_ids=[],
    )


def diagnosis_report(cause: RootCause, number: int) -> DiagnosisReport:
    return DiagnosisReport(
        diagnosis_id=f"synthetic-diagnosis-{number}",
        generated_at=datetime(2026, 8, 11, 12, 0, 2, tzinfo=UTC),
        analyzed_window=AnalysisWindow(
            start=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
            end=datetime(2026, 8, 11, 12, 0, 1, tzinfo=UTC),
        ),
        input_context=InputContextSummary(
            total_requests=1, request_id_count=1, trace_id_count=0
        ),
        suspected_root_cause=cause,
        affected_service=None if cause is RootCause.NONE else "inventory",
        confidence=0.75,
        confidence_level="medium",
        summary="Synthetic deterministic diagnosis.",
        candidate_scores={cause: CandidateScore(score=0.75)},
        evidence=[],
        alternative_causes=[],
        telemetry_coverage=TelemetryCoverage(
            metrics=SourceStatus.AVAILABLE,
            logs=SourceStatus.AVAILABLE,
            traces=SourceStatus.AVAILABLE,
        ),
        warnings=[],
        recommended_checks=["Inspect the synthetic fixture."],
    )


class FakeScenarios:
    def __init__(
        self, root: Path, events: list[str], fail_calls: set[int] | None = None
    ):
        self.root = root
        self.events = events
        self.fail_calls = fail_calls or set()
        self.calls: list[ScenarioName] = []
        self.reset_calls = 0

    async def run(self, scenario, parameters):
        del parameters
        number = len(self.calls) + 1
        self.calls.append(scenario)
        self.events.append(f"scenario:{scenario.value}:{number}")
        if number in self.fail_calls:
            raise RuntimeError("private scenario detail")
        report = incident_report(scenario, number)
        path = self.root / f"private-revealing-{scenario.value}-{number}.json"
        path.write_text(json.dumps(report.as_dict()), encoding="utf-8")
        return report, path

    async def reset(self):
        self.reset_calls += 1
        self.events.append("reset")


class FakeDiagnoses:
    def __init__(
        self,
        root: Path,
        events: list[str],
        causes: list[RootCause],
        fail_calls: set[int] | None = None,
    ):
        self.root = root
        self.events = events
        self.causes = causes
        self.fail_calls = fail_calls or set()
        self.context_keys: list[set[str]] = []
        self.paths: list[Path] = []

    async def diagnose(self, incident_path: Path):
        number = len(self.context_keys) + 1
        context = load_analysis_context(incident_path)
        self.context_keys.append(set(context.model_dump()))
        self.events.append(f"diagnose:{number}")
        if number in self.fail_calls:
            raise RuntimeError("private telemetry detail")
        report = diagnosis_report(self.causes[number - 1], number)
        path = write_diagnosis_report(report, self.root)
        self.paths.append(path)
        self.events.append(f"diagnosis-written:{number}")
        return report, path, 12.5


class FakeEvaluations:
    def __init__(self, events: list[str], fail: bool = False):
        self.events = events
        self.fail = fail

    def evaluate(self, diagnosis_path: Path, incident_path: Path):
        number = (
            len([event for event in self.events if event.startswith("evaluate:")]) + 1
        )
        assert diagnosis_path.is_file()
        assert f"diagnosis-written:{number}" in self.events
        self.events.append(f"evaluate:{number}")
        if self.fail:
            raise RuntimeError("private evaluation detail")
        return evaluate_existing_diagnosis(diagnosis_path, incident_path)
