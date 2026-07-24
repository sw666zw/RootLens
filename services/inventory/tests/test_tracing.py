"""OpenTelemetry tracing tests for the Inventory Service."""

import io
import json
import logging
import warnings
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient as FastAPITestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.database import get_database_session
from inventory_service.logging_config import JsonFormatter, configure_logging
from inventory_service.main import create_app
from inventory_service.repositories import inventory_items
from inventory_service.tracing import (
    TracingConfiguration,
    TracingSettings,
)


def tracing_configuration(
    exporter: InMemorySpanExporter,
) -> TracingConfiguration:
    return TracingConfiguration(
        settings=TracingSettings(
            enabled=True,
            service_name="rootlens-inventory",
            exporter_endpoint="unused:4317",
            exporter_insecure=True,
            sampler_name="always_on",
        ),
        span_exporter=exporter,
        span_processor_factory=SimpleSpanProcessor,
    )


def traced_application(
    exporter: InMemorySpanExporter,
) -> Any:
    application = create_app(tracing=tracing_configuration(exporter))

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    application.dependency_overrides[get_database_session] = override_session
    return application


def server_spans(exporter: InMemorySpanExporter) -> list[Any]:
    return [
        span
        for span in exporter.get_finished_spans()
        if span.kind is trace.SpanKind.SERVER
    ]


def test_tracing_disabled_does_not_create_an_exporter(monkeypatch: Any) -> None:
    exporter = Mock(side_effect=AssertionError("network exporter was constructed"))
    monkeypatch.setattr(
        "inventory_service.tracing.OTLPSpanExporter",
        exporter,
    )

    application = create_app()
    response = FastAPITestClient(application).get("/health")

    assert application.state.tracing is None
    assert exporter.call_count == 0
    assert response.status_code == 200
    assert "X-Trace-ID" not in response.headers


def test_repeated_disabled_application_creation_has_no_provider_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        first = create_app()
        second = create_app()

    assert first.state.tracing is None
    assert second.state.tracing is None
    assert not [
        warning
        for warning in caught
        if "TracerProvider" in str(warning.message)
        or "instrument" in str(warning.message).lower()
    ]


def test_repeated_traced_application_creation_is_app_scoped() -> None:
    first_exporter = InMemorySpanExporter()
    second_exporter = InMemorySpanExporter()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        first = traced_application(first_exporter)
        second = traced_application(second_exporter)
        with FastAPITestClient(first) as first_client:
            first_client.get("/health")
        with FastAPITestClient(second) as second_client:
            second_client.get("/health")

    assert first.state.tracing is not second.state.tracing
    assert (
        first.state.database_resources.engine
        is not second.state.database_resources.engine
    )
    assert not [
        warning
        for warning in caught
        if "TracerProvider" in str(warning.message)
        or "instrument" in str(warning.message).lower()
    ]

    assert len(server_spans(first_exporter)) == 1
    assert len(server_spans(second_exporter)) == 1


def test_health_produces_server_span_and_trace_headers() -> None:
    exporter = InMemorySpanExporter()
    application = traced_application(exporter)

    with FastAPITestClient(application) as client:
        response = client.get(
            "/health",
            headers={"X-Request-ID": "trace-request-id"},
        )

    spans = server_spans(exporter)
    assert len(spans) == 1
    assert spans[0].name == "GET /health"
    assert spans[0].attributes["http.route"] == "/health"
    assert spans[0].attributes["rootlens.request_id"] == "trace-request-id"
    assert spans[0].resource.attributes["service.name"] == "rootlens-inventory"
    assert spans[0].resource.attributes["service.namespace"] == "rootlens"
    assert spans[0].resource.attributes["deployment.environment.name"] == "local"
    assert response.headers["X-Request-ID"] == "trace-request-id"
    assert response.headers["X-Trace-ID"] == f"{spans[0].context.trace_id:032x}"


def test_metrics_is_excluded_from_tracing() -> None:
    exporter = InMemorySpanExporter()
    application = traced_application(exporter)

    with FastAPITestClient(application) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "X-Trace-ID" not in response.headers
    assert server_spans(exporter) == []


def test_item_skus_use_the_same_normalized_server_span(monkeypatch: Any) -> None:
    async def missing_item(session: AsyncSession, sku: str) -> None:
        return None

    monkeypatch.setattr(inventory_items, "get_inventory_item_by_sku", missing_item)
    exporter = InMemorySpanExporter()
    application = traced_application(exporter)

    with FastAPITestClient(application) as client:
        client.get("/items/LAPTOP-001")
        client.get("/items/PHONE-002")

    spans = server_spans(exporter)
    assert [span.name for span in spans] == [
        "GET /items/{sku}",
        "GET /items/{sku}",
    ]
    assert {span.attributes["http.route"] for span in spans} == {"/items/{sku}"}
    assert all("LAPTOP-001" not in span.name for span in spans)
    assert all("PHONE-002" not in span.name for span in spans)


def test_incoming_traceparent_is_honored() -> None:
    exporter = InMemorySpanExporter()
    application = traced_application(exporter)
    incoming_trace_id = "0af7651916cd43dd8448eb211c80319c"
    incoming_parent_id = "b7ad6b7169203331"

    with FastAPITestClient(application) as client:
        response = client.get(
            "/health",
            headers={
                "traceparent": (f"00-{incoming_trace_id}-{incoming_parent_id}-01")
            },
        )

    span = server_spans(exporter)[0]
    assert f"{span.context.trace_id:032x}" == incoming_trace_id
    assert f"{span.parent.span_id:016x}" == incoming_parent_id
    assert response.headers["X-Trace-ID"] == incoming_trace_id


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (None, "success"),
        (inventory_items.InventoryItemNotFoundError, "item_not_found"),
        (
            inventory_items.InsufficientInventoryError,
            "insufficient_inventory",
        ),
        (
            inventory_items.InventoryReservationDatabaseError,
            "database_error",
        ),
    ],
)
def test_reservation_span_has_safe_domain_attributes(
    monkeypatch: Any,
    error: type[Exception] | None,
    outcome: str,
) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        if error is not None:
            if error is inventory_items.InventoryReservationDatabaseError:
                raise error from RuntimeError(
                    "postgresql+asyncpg://user:password@database/inventory"
                )
            raise error
        return inventory_items.InventoryReservationResult(sku, quantity, 4)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)
    exporter = InMemorySpanExporter()
    application = traced_application(exporter)

    with FastAPITestClient(application) as client:
        client.post(
            "/items/SAFE-SKU/reserve",
            headers={"X-Request-ID": "reservation-trace-id"},
            json={"quantity": 2},
        )

    span = server_spans(exporter)[0]
    assert span.attributes["rootlens.request_id"] == "reservation-trace-id"
    assert span.attributes["rootlens.inventory.operation"] == "reserve"
    assert span.attributes["rootlens.inventory.sku"] == "SAFE-SKU"
    assert span.attributes["rootlens.inventory.requested_quantity"] == 2
    assert span.attributes["rootlens.inventory.outcome"] == outcome

    if outcome == "database_error":
        assert span.status.status_code is StatusCode.ERROR
        assert any(event.name == "exception" for event in span.events)
        event_text = json.dumps([dict(event.attributes or {}) for event in span.events])
        assert "postgresql+asyncpg://" not in event_text
        assert "password" not in event_text


def test_structured_log_includes_valid_active_trace_ids() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(__name__)
    record = logging.LogRecord(
        name="inventory_service.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="correlated",
        args=(),
        exc_info=None,
    )

    with tracer.start_as_current_span("test") as span:
        payload = json.loads(JsonFormatter().format(record))
        assert payload["trace_id"] == f"{span.get_span_context().trace_id:032x}"
        assert payload["span_id"] == f"{span.get_span_context().span_id:016x}"

    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16
    assert payload["trace_id"] == payload["trace_id"].lower()
    assert payload["span_id"] == payload["span_id"].lower()
    provider.shutdown()


def test_structured_log_omits_ids_without_active_span() -> None:
    record = logging.LogRecord(
        name="inventory_service.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="uncorrelated",
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert "trace_id" not in payload
    assert "span_id" not in payload


def test_request_and_reservation_logs_share_the_server_trace(
    monkeypatch: Any,
) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        return inventory_items.InventoryReservationResult(sku, quantity, 4)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)
    output = io.StringIO()
    configure_logging(output)
    exporter = InMemorySpanExporter()
    application = traced_application(exporter)

    with FastAPITestClient(application) as client:
        client.post(
            "/items/LOG-SKU/reserve",
            headers={"X-Request-ID": "log-trace-request"},
            json={"quantity": 1},
        )

    span = server_spans(exporter)[0]
    expected_trace_id = f"{span.context.trace_id:032x}"
    logs = [json.loads(line) for line in output.getvalue().splitlines()]
    correlated = [
        log
        for log in logs
        if log["message"] in {"inventory_reservation_succeeded", "request_completed"}
    ]
    assert len(correlated) == 2
    assert all(log["trace_id"] == expected_trace_id for log in correlated)
    assert all(len(log["span_id"]) == 16 for log in correlated)


def test_sqlalchemy_instrumentation_is_applied_once(monkeypatch: Any) -> None:
    instrument = Mock()
    monkeypatch.setattr(
        "inventory_service.tracing.SQLAlchemyInstrumentor.instrument",
        instrument,
    )
    monkeypatch.setattr(
        "inventory_service.tracing.FastAPIInstrumentor.instrument_app",
        Mock(),
    )
    exporter = InMemorySpanExporter()
    application = create_app(tracing=tracing_configuration(exporter))
    application.state.tracing.start()

    assert application.state.tracing is not None
    assert instrument.call_count == 1
    assert instrument.call_args.kwargs["engine"] is (
        application.state.database_resources.engine.sync_engine
    )
