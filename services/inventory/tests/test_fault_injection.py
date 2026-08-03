"""Development-only Inventory fault injection behavior."""

import io
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient as FastAPITestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.database import check_database_readiness, get_database_session
from inventory_service.faults import ReservationFaultController
from inventory_service.logging_config import configure_logging
from inventory_service.main import create_app
from inventory_service.repositories import inventory_items
from inventory_service.tracing import (
    TracingConfiguration,
    TracingSettings,
)

LOOPBACK = ("127.0.0.1", 50000)
FAULT_PATH = "/internal/faults/reservation"


def make_application(*, enabled: bool = True) -> Any:
    application = create_app(enable_fault_injection=enabled)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    application.dependency_overrides[get_database_session] = override_session
    return application


def make_client(*, enabled: bool = True) -> FastAPITestClient:
    return FastAPITestClient(make_application(enabled=enabled), client=LOOPBACK)


def test_fault_endpoints_are_absent_when_disabled() -> None:
    application = make_application(enabled=False)
    response = FastAPITestClient(application, client=LOOPBACK).get(FAULT_PATH)

    assert response.status_code == 404
    assert not hasattr(application.state, "fault_controller")


def test_fault_endpoints_are_hidden_and_registered_when_enabled() -> None:
    client = make_client()

    response = client.get(FAULT_PATH)

    assert response.status_code == 200
    assert FAULT_PATH not in client.get("/openapi.json").json()["paths"]


def test_fault_endpoints_reject_non_loopback_clients() -> None:
    application = make_application()
    client = FastAPITestClient(application, client=("192.0.2.10", 50000))

    response = client.get(FAULT_PATH)

    assert response.status_code == 403


def test_fault_configuration_can_be_read_updated_and_reset() -> None:
    client = make_client()
    default = {"delay_ms": 0, "failure_mode": "none"}

    assert client.get(FAULT_PATH).json() == default
    updated = client.put(
        FAULT_PATH,
        json={"delay_ms": 1500, "failure_mode": "service_unavailable"},
    )
    reset = client.delete(FAULT_PATH)

    assert updated.status_code == 200
    assert updated.json() == {
        "delay_ms": 1500,
        "failure_mode": "service_unavailable",
    }
    assert reset.json() == default


def test_fault_configuration_rejects_invalid_values() -> None:
    client = make_client()

    for payload in (
        {"delay_ms": -1, "failure_mode": "none"},
        {"delay_ms": 10001, "failure_mode": "none"},
        {"delay_ms": 1, "failure_mode": "unknown"},
        {"delay_ms": True, "failure_mode": "none"},
    ):
        assert client.put(FAULT_PATH, json=payload).status_code == 422


def test_delay_uses_async_sleep_then_continues_reservation(
    monkeypatch: Any,
) -> None:
    sleeps: list[float] = []
    repository_calls = 0

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async def reserve(
        session: AsyncSession, sku: str, quantity: int
    ) -> inventory_items.InventoryReservationResult:
        nonlocal repository_calls
        repository_calls += 1
        return inventory_items.InventoryReservationResult(sku, quantity, 7)

    monkeypatch.setattr("inventory_service.api.items.asyncio.sleep", sleep)
    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve)
    client = make_client()
    client.put(FAULT_PATH, json={"delay_ms": 250, "failure_mode": "none"})

    response = client.post("/items/SKU-001/reserve", json={"quantity": 1})

    assert response.status_code == 200
    assert sleeps == [0.25]
    assert repository_calls == 1


def test_service_unavailable_is_exact_and_never_calls_repository(
    monkeypatch: Any,
) -> None:
    calls = 0
    quantity = 10

    async def reserve(*args: object) -> None:
        nonlocal calls, quantity
        calls += 1
        quantity -= 1

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve)
    client = make_client()
    client.put(
        FAULT_PATH,
        json={"delay_ms": 0, "failure_mode": "service_unavailable"},
    )

    response = client.post("/items/SKU-001/reserve", json={"quantity": 1})

    assert response.status_code == 503
    assert response.json() == {"detail": "Inventory service unavailable."}
    assert calls == 0
    assert quantity == 10


def test_unrelated_endpoints_are_unaffected(monkeypatch: Any) -> None:
    now = datetime.now(UTC)

    async def list_items(session: AsyncSession) -> list[object]:
        return []

    async def create_item(session: AsyncSession, item_data: Any) -> SimpleNamespace:
        return SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            sku=item_data.sku,
            name=item_data.name,
            quantity=item_data.quantity,
            created_at=now,
            updated_at=now,
        )

    async def get_item(session: AsyncSession, sku: str) -> SimpleNamespace:
        return SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            sku=sku,
            name="Unaffected",
            quantity=10,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(inventory_items, "list_inventory_items", list_items)
    monkeypatch.setattr(inventory_items, "create_inventory_item", create_item)
    monkeypatch.setattr(inventory_items, "get_inventory_item_by_sku", get_item)
    application = make_application()
    application.dependency_overrides[check_database_readiness] = lambda: True
    client = FastAPITestClient(application, client=LOOPBACK)
    client.put(
        FAULT_PATH,
        json={"delay_ms": 10000, "failure_mode": "service_unavailable"},
    )

    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert (
        client.post(
            "/items", json={"sku": "SKU-NEW", "name": "New", "quantity": 2}
        ).status_code
        == 201
    )
    assert client.get("/items").json() == []
    assert client.get("/items/SKU-001").status_code == 200


def test_fault_controls_are_excluded_from_metrics_and_completion_logs() -> None:
    output = io.StringIO()
    configure_logging(output)
    client = make_client()

    client.get(FAULT_PATH)
    client.get("/health")
    metrics = client.get("/metrics").text
    logs = [json.loads(line) for line in output.getvalue().splitlines()]

    assert "/internal/faults" not in metrics
    assert 'route="/health"' in metrics
    assert any(
        log.get("message") == "request_completed" and log.get("path") == "/health"
        for log in logs
    )
    assert not any(
        log.get("message") == "request_completed"
        and str(log.get("path", "")).startswith("/internal/faults")
        for log in logs
    )


def test_fault_controls_are_excluded_from_tracing() -> None:
    exporter = InMemorySpanExporter()
    tracing = TracingConfiguration(
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
    application = create_app(tracing=tracing, enable_fault_injection=True)

    with FastAPITestClient(application, client=LOOPBACK) as client:
        response = client.get(FAULT_PATH)

    assert response.status_code == 200
    assert exporter.get_finished_spans() == ()
    assert "X-Trace-ID" not in response.headers


def test_repeated_applications_do_not_share_fault_state() -> None:
    first = make_client()
    second = make_client()

    first.put(
        FAULT_PATH,
        json={"delay_ms": 500, "failure_mode": "service_unavailable"},
    )

    assert first.get(FAULT_PATH).json()["delay_ms"] == 500
    assert second.get(FAULT_PATH).json() == {
        "delay_ms": 0,
        "failure_mode": "none",
    }


def test_controller_can_be_replaced_for_one_application() -> None:
    controller = ReservationFaultController()
    application = create_app(
        enable_fault_injection=True,
        fault_controller=controller,
    )

    assert application.state.fault_controller is controller
