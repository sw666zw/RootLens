"""Application-scoped tracing and correlation headers."""

from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from diagnosis_service.main import create_app
from diagnosis_service.tracing import TracingConfiguration, TracingSettings


def _tracing(exporter: InMemorySpanExporter) -> TracingConfiguration:
    return TracingConfiguration(
        TracingSettings(True, "rootlens-diagnosis", "unused:4317", True, "always_on"),
        exporter,
        SimpleSpanProcessor,
    )


def test_trace_header_coexists_with_request_id(settings, fake_diagnosis):
    exporter = InMemorySpanExporter()
    app = create_app(
        settings,
        diagnosis_service=fake_diagnosis,
        tracing=_tracing(exporter),
    )
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    parent_id = "b7ad6b7169203331"
    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={
                "X-Request-ID": "caller-request",
                "traceparent": f"00-{trace_id}-{parent_id}-01",
            },
        )
    spans = [
        span
        for span in exporter.get_finished_spans()
        if span.kind is trace.SpanKind.SERVER
    ]
    assert len(spans) == 1
    assert response.headers["X-Request-ID"] == "caller-request"
    assert response.headers["X-Trace-ID"] == trace_id
    assert spans[0].attributes["rootlens.request_id"] == "caller-request"


def test_metrics_is_excluded_from_tracing(settings, fake_diagnosis):
    exporter = InMemorySpanExporter()
    app = create_app(
        settings,
        diagnosis_service=fake_diagnosis,
        tracing=_tracing(exporter),
    )
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "X-Trace-ID" not in response.headers
    assert exporter.get_finished_spans() == ()
