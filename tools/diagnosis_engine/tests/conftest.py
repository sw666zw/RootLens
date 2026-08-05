"""Diagnosis-engine fixtures with no external services."""

from datetime import UTC, datetime

import pytest

from rootlens_diagnosis.engine import DiagnosisEngine
from rootlens_diagnosis.explanation_providers import OpenAIExplanationProvider
from rootlens_diagnosis.incident_context import (
    AnalysisWindow,
    IncidentAnalysisContext,
)
from rootlens_diagnosis.models import DiagnosisReport, SourceStatus
from rootlens_diagnosis.telemetry.models import (
    LogFeatures,
    MetricsFeatures,
    NormalizedTelemetry,
    SourceResult,
    TraceFeatures,
)

EXPLANATION_ENV_WITH_TEST_DEFAULTS = {
    "ROOTLENS_EXPLANATION_PROVIDER": "template",
    "ROOTLENS_LLM_ENABLED": "false",
}
EXPLANATION_ENV_TO_CLEAR = (
    "ROOTLENS_EXPLANATION_OUTPUT_DIR",
    "ROOTLENS_LLM_TIMEOUT_SECONDS",
    "ROOTLENS_LLM_MAX_OUTPUT_TOKENS",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
)


@pytest.fixture(autouse=True)
def isolate_explanation_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests offline and independent from private shell or .env values."""
    for name, value in EXPLANATION_ENV_WITH_TEST_DEFAULTS.items():
        monkeypatch.setenv(name, value)
    for name in EXPLANATION_ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)

    def forbid_real_openai_client(_provider: OpenAIExplanationProvider) -> None:
        raise AssertionError("tests must inject an OpenAI client or fake provider")

    monkeypatch.setattr(
        OpenAIExplanationProvider,
        "_create_client",
        forbid_real_openai_client,
    )


@pytest.fixture
def context() -> IncidentAnalysisContext:
    return IncidentAnalysisContext(
        started_at="2026-08-03T20:00:00Z",
        ended_at="2026-08-03T20:00:20Z",
        request_ids=("request-1", "request-2"),
        trace_ids=("0af7651916cd43dd8448eb211c80319c",),
        total_requests=20,
        inventory_sku="SAFE-SKU",
        concurrency=5,
    )


@pytest.fixture
def window() -> AnalysisWindow:
    return AnalysisWindow(
        start=datetime(2026, 8, 3, 19, 59, 45, tzinfo=UTC),
        end=datetime(2026, 8, 3, 20, 0, 35, tzinfo=UTC),
    )


def telemetry(
    metrics: MetricsFeatures,
    logs: LogFeatures,
    traces: TraceFeatures,
    *,
    statuses: tuple[SourceStatus, SourceStatus, SourceStatus] = (
        SourceStatus.AVAILABLE,
        SourceStatus.AVAILABLE,
        SourceStatus.AVAILABLE,
    ),
) -> NormalizedTelemetry:
    return NormalizedTelemetry(
        SourceResult(statuses[0], metrics),
        SourceResult(statuses[1], logs),
        SourceResult(statuses[2], traces),
    )


@pytest.fixture
def healthy_telemetry() -> NormalizedTelemetry:
    return telemetry(
        MetricsFeatures(
            order_requests=20,
            order_5xx=0,
            order_503=0,
            order_p95_ms=80,
            inventory_requests=20,
            inventory_5xx=0,
            inventory_503=0,
            inventory_p95_ms=50,
            order_confirmed=20,
            order_failed=0,
            reservation_success=20,
            reservation_failed=0,
            order_up_ratio=1,
            inventory_up_ratio=1,
        ),
        LogFeatures(
            categories={
                "order_creation_succeeded": 20,
                "inventory_reservation_succeeded": 20,
            }
        ),
        TraceFeatures(
            trace_count=20,
            cross_service_count=20,
            successful_reservations=20,
            order_server_p95_ms=80,
            inventory_server_p95_ms=50,
            order_inventory_client_p95_ms=55,
            slowest_service="order",
            slowest_span_category="http_server",
        ),
    )


@pytest.fixture
def slow_telemetry() -> NormalizedTelemetry:
    return telemetry(
        MetricsFeatures(
            order_requests=20,
            order_5xx=0,
            order_p95_ms=1600,
            inventory_requests=20,
            inventory_5xx=0,
            inventory_p95_ms=1500,
            order_confirmed=20,
            reservation_success=20,
            order_up_ratio=1,
            inventory_up_ratio=1,
        ),
        LogFeatures(
            categories={
                "order_creation_succeeded": 20,
                "inventory_reservation_succeeded": 20,
            }
        ),
        TraceFeatures(
            trace_count=20,
            cross_service_count=20,
            successful_reservations=20,
            order_server_p95_ms=1600,
            inventory_server_p95_ms=1500,
            order_inventory_client_p95_ms=1510,
            slowest_service="inventory",
            slowest_span_category="http_server",
        ),
    )


@pytest.fixture
def unavailable_telemetry() -> NormalizedTelemetry:
    return telemetry(
        MetricsFeatures(
            order_requests=20,
            order_5xx=20,
            order_503=20,
            inventory_requests=20,
            inventory_5xx=20,
            inventory_503=20,
            order_failed=20,
            reservation_failed=20,
            order_up_ratio=1,
            inventory_up_ratio=1,
        ),
        LogFeatures(
            categories={"order_creation_failed": 20},
            reasons={"inventory_unavailable": 20},
        ),
        TraceFeatures(
            trace_count=20,
            cross_service_count=20,
            failed_inventory_traces=20,
            failed_without_database=20,
            error_span_count=40,
            slowest_service="inventory",
        ),
    )


@pytest.fixture
def diagnosis_report(
    context: IncidentAnalysisContext,
    window: AnalysisWindow,
    healthy_telemetry: NormalizedTelemetry,
) -> DiagnosisReport:
    return DiagnosisEngine().analyze(
        context,
        window,
        healthy_telemetry,
        diagnosis_id="diagnosis-safe-test",
        generated_at=datetime(2026, 8, 3, 21, 0, tzinfo=UTC),
    )
