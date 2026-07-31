"""Distributed tracing and log-correlation tests."""

import io
import json
import warnings
from typing import Any
from unittest.mock import Mock

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from test_support.order import (
    InMemoryOrdersRepository,
    make_client,
    successful_inventory,
)

from order_service.api.orders import get_order_repository
from order_service.database import get_database_session
from order_service.logging_config import configure_logging
from order_service.tracing import TracingConfiguration, TracingSettings


def tracing_configuration(
    exporter: InMemorySpanExporter,
) -> TracingConfiguration:
    return TracingConfiguration(
        settings=TracingSettings(
            enabled=True,
            service_name="rootlens-order",
            exporter_endpoint="unused:4317",
            exporter_insecure=True,
            sampler_name="always_on",
        ),
        span_exporter=exporter,
        span_processor_factory=SimpleSpanProcessor,
    )


def test_incoming_context_outgoing_propagation_and_correlation() -> None:
    exporter = InMemorySpanExporter()
    output = io.StringIO()
    configure_logging(output)
    outgoing_traceparent: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal outgoing_traceparent
        outgoing_traceparent = request.headers.get("traceparent")
        return successful_inventory(request)

    incoming_trace_id = "0af7651916cd43dd8448eb211c80319c"
    incoming_parent_id = "b7ad6b7169203331"
    with make_client(handler, tracing_configuration(exporter)) as client:
        response = client.post(
            "/orders",
            headers={
                "X-Request-ID": "correlated-request",
                "traceparent": f"00-{incoming_trace_id}-{incoming_parent_id}-01",
            },
            json={"sku": "SKU-001", "quantity": 1},
        )

    spans = exporter.get_finished_spans()
    server = next(span for span in spans if span.kind is trace.SpanKind.SERVER)
    client_span = next(span for span in spans if span.kind is trace.SpanKind.CLIENT)
    assert f"{server.context.trace_id:032x}" == incoming_trace_id
    assert f"{server.parent.span_id:016x}" == incoming_parent_id
    assert client_span.context.trace_id == server.context.trace_id
    assert client_span.parent.span_id == server.context.span_id
    assert outgoing_traceparent is not None
    assert outgoing_traceparent.split("-")[1] == incoming_trace_id
    assert response.headers["X-Request-ID"] == "correlated-request"
    assert response.headers["X-Trace-ID"] == incoming_trace_id
    assert server.attributes["rootlens.request_id"] == "correlated-request"
    assert server.attributes["rootlens.order.operation"] == "create"
    assert len(server.attributes["rootlens.order.id"]) == 36
    assert server.attributes["rootlens.order.persisted"] is True
    assert server.attributes["rootlens.order.status"] == "confirmed"
    assert server.attributes["rootlens.order.sku"] == "SKU-001"
    assert server.attributes["rootlens.order.quantity"] == 1
    assert server.attributes["rootlens.order.outcome"] == "confirmed"

    logs = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if "order_creation_succeeded" in line or "request_completed" in line
    ]
    assert len(logs) == 2
    assert all(item["request_id"] == "correlated-request" for item in logs)
    assert all(item["trace_id"] == incoming_trace_id for item in logs)
    assert all(len(str(item["span_id"])) == 16 for item in logs)
    assert {span.name for span in spans} >= {
        "order.persist_pending",
        "order.persist_result",
    }


def test_replay_trace_has_safe_outcome_and_no_second_inventory_span() -> None:
    exporter = InMemorySpanExporter()
    with make_client(
        successful_inventory,
        tracing_configuration(exporter),
    ) as client:
        first = client.post(
            "/orders",
            headers={"Idempotency-Key": "trace-private-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )
        replay = client.post(
            "/orders",
            headers={
                "Idempotency-Key": "trace-private-key",
                "X-Request-ID": "replay-request",
            },
            json={"sku": "SKU-001", "quantity": 1},
        )

    spans = exporter.get_finished_spans()
    servers = [span for span in spans if span.kind is trace.SpanKind.SERVER]
    clients = [span for span in spans if span.kind is trace.SpanKind.CLIENT]
    replay_span = next(
        span
        for span in servers
        if span.attributes.get("rootlens.request_id") == "replay-request"
    )
    assert first.status_code == replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.headers["X-Request-ID"] == "replay-request"
    assert "X-Trace-ID" in replay.headers
    assert len(clients) == 1
    assert replay_span.attributes["rootlens.order.idempotency_key_present"] is True
    assert replay_span.attributes["rootlens.order.idempotency_outcome"] == "replayed"
    assert "trace-private-key" not in str(replay_span.attributes)
    assert "request_fingerprint" not in str(replay_span.attributes)


def test_metrics_excluded_and_repeated_apps_do_not_warn() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        first_exporter = InMemorySpanExporter()
        second_exporter = InMemorySpanExporter()
        with make_client(
            successful_inventory,
            tracing_configuration(first_exporter),
        ) as first:
            response = first.get("/metrics")
        with make_client(
            successful_inventory,
            tracing_configuration(second_exporter),
        ) as second:
            second.get("/health")

    assert response.status_code == 200
    assert "X-Trace-ID" not in response.headers
    assert not first_exporter.get_finished_spans()
    assert (
        len(
            [
                span
                for span in second_exporter.get_finished_spans()
                if span.kind is trace.SpanKind.SERVER
            ]
        )
        == 1
    )
    assert not [
        warning
        for warning in caught
        if "instrument" in str(warning.message).lower()
        or "TracerProvider" in str(warning.message)
    ]


def test_http_client_is_reused_and_closed() -> None:
    clients: list[httpx.AsyncClient] = []

    def factory(_: Any) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            base_url="http://inventory.test",
            transport=httpx.MockTransport(successful_inventory),
        )
        clients.append(client)
        return client

    from fastapi.testclient import TestClient as FastAPITestClient

    from order_service.main import create_app

    application = create_app(http_client_factory=factory)

    async def override_session() -> Any:
        yield object()

    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_order_repository] = InMemoryOrdersRepository
    with FastAPITestClient(application) as client:
        first_owned = application.state.http_client
        client.post("/orders", json={"sku": "SKU-001", "quantity": 1})
        client.post("/orders", json={"sku": "SKU-001", "quantity": 1})
        assert application.state.http_client is first_owned
        assert not first_owned.is_closed

    assert len(clients) == 1
    assert clients[0].is_closed


def test_sqlalchemy_instrumentation_is_applied_once(monkeypatch: Any) -> None:
    instrument = Mock()
    monkeypatch.setattr(
        "order_service.tracing.SQLAlchemyInstrumentor.instrument",
        instrument,
    )
    monkeypatch.setattr(
        "order_service.tracing.SQLAlchemyInstrumentor.uninstrument",
        Mock(),
    )
    monkeypatch.setattr(
        "order_service.tracing.FastAPIInstrumentor.instrument_app",
        Mock(),
    )
    exporter = InMemorySpanExporter()

    with make_client(
        successful_inventory,
        tracing_configuration(exporter),
    ) as client:
        client.get("/health")

    assert instrument.call_count == 1
