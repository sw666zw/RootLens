"""Curated documentation artifacts preserve the production schemas."""

import json
from pathlib import Path

from rootlens_diagnosis.explanation_models import ExplanationReport
from rootlens_diagnosis.models import DiagnosisReport
from rootlens_scenarios.models import IncidentReport

from rootlens_benchmark.models import BenchmarkReport

EXAMPLES = Path(__file__).parents[3] / "docs" / "examples"


def load(name: str) -> dict[str, object]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_curated_examples_match_runtime_schemas() -> None:
    incident = IncidentReport(**load("incident-report.example.json"))
    diagnosis = DiagnosisReport.model_validate(load("diagnosis-report.example.json"))
    explanation = ExplanationReport.model_validate(
        load("template-explanation-report.example.json")
    )
    benchmark = BenchmarkReport.model_validate(load("benchmark-summary.example.json"))

    assert incident.scenario_id.startswith("example-")
    assert diagnosis.diagnosis_id.startswith("example-")
    assert explanation.provider == "template"
    assert explanation.provider_response_id is None
    assert benchmark.benchmark_id.startswith("example-")
