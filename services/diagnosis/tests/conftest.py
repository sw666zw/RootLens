"""Isolated Diagnosis Service fixtures."""

import json
import os
from datetime import timedelta
from pathlib import Path

os.environ["ROOTLENS_EXPLANATION_PROVIDER"] = "template"
os.environ["ROOTLENS_LLM_ENABLED"] = "false"
os.environ.pop("OPENAI_API_KEY", None)

import pytest
from fastapi.testclient import TestClient
from rootlens_diagnosis.config import DiagnosisConfig, ExplanationConfig
from rootlens_diagnosis.engine import DiagnosisEngine, empty_telemetry
from rootlens_diagnosis.incident_context import (
    AnalysisWindow,
    IncidentAnalysisContext,
    load_analysis_context,
)
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.reports import write_diagnosis_report

from diagnosis_service.config import Settings
from diagnosis_service.main import create_app
from diagnosis_service.tracing import TracingConfiguration, TracingSettings


def incident_payload(scenario_id: str = "baseline-20260805-abc") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "scenario_name": "baseline",
        "started_at": "2026-08-05T12:00:00Z",
        "ended_at": "2026-08-05T12:00:10Z",
        "target_service": "inventory",
        "parameters": {"requests": 2, "concurrency": 1},
        "expected_root_cause": "none",
        "expected_symptoms": ["orders succeed"],
        "inventory_sku": "SAFE-SKU",
        "total_requests": 2,
        "concurrency": 1,
        "response_status_counts": {"201": 2},
        "successful_requests": 2,
        "failed_requests": 0,
        "request_ids": ["request-1", "request-2"],
        "trace_ids": [],
    }


def make_report(path: Path | None = None):
    if path is None:
        context = IncidentAnalysisContext(
            started_at="2026-08-05T12:00:00Z",
            ended_at="2026-08-05T12:00:10Z",
            request_ids=("request-1",),
            trace_ids=(),
            total_requests=1,
            concurrency=1,
        )
    else:
        context = load_analysis_context(path)
    window = AnalysisWindow(
        start=context.started_at - timedelta(seconds=1),
        end=context.ended_at + timedelta(seconds=1),
    )
    return DiagnosisEngine().analyze(
        context, window, empty_telemetry(SourceStatus.AVAILABLE)
    )


class FakeDiagnosisService:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.incident_paths: list[Path] = []

    async def diagnose(
        self,
        incident_path: Path,
        *,
        require_all_sources: bool,
        window_padding_seconds: int | None,
    ):
        del require_all_sources, window_padding_seconds
        self.incident_paths.append(incident_path)
        report = make_report(incident_path)
        write_diagnosis_report(report, self.output_dir)
        return report


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    incidents = tmp_path / "incidents"
    diagnoses = tmp_path / "diagnoses"
    explanations = tmp_path / "explanations"
    incidents.mkdir()
    diagnoses.mkdir()
    explanations.mkdir()
    (incidents / "baseline-20260805-abc.json").write_text(
        json.dumps(incident_payload()), encoding="utf-8"
    )
    return Settings(
        host="127.0.0.1",
        port=8002,
        incident_output_dir=incidents,
        diagnosis=DiagnosisConfig(
            prometheus_url="http://prometheus.test",
            loki_url="http://loki.test",
            jaeger_url="http://jaeger.test",
            output_dir=diagnoses,
            window_padding_seconds=15,
            timeout_seconds=1,
        ),
        explanation=ExplanationConfig(
            provider="template",
            llm_enabled=False,
            output_dir=explanations,
            timeout_seconds=1,
            max_output_tokens=100,
            openai_api_key=None,
            openai_model="gpt-5-mini",
        ),
    )


@pytest.fixture
def fake_diagnosis(settings: Settings) -> FakeDiagnosisService:
    return FakeDiagnosisService(settings.diagnosis.output_dir)


@pytest.fixture
def client(settings: Settings, fake_diagnosis: FakeDiagnosisService) -> TestClient:
    tracing = TracingConfiguration(
        TracingSettings(False, "test", "http://collector.test", True, "always_on")
    )
    with TestClient(
        create_app(
            settings,
            diagnosis_service=fake_diagnosis,
            tracing=tracing,
        )
    ) as test_client:
        yield test_client
