"""Prometheus metrics tests for the Inventory Service."""

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient as FastAPITestClient
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.database import get_database_session
from inventory_service.main import create_app
from inventory_service.repositories import inventory_items


def make_client() -> FastAPITestClient:
    application = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    application.dependency_overrides[get_database_session] = override_session
    return FastAPITestClient(application)


def scrape(client: FastAPITestClient) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    return response.text


def sample_values(
    exposition: str,
    name: str,
    labels: dict[str, str],
) -> list[float]:
    return [
        sample.value
        for family in text_string_to_metric_families(exposition)
        for sample in family.samples
        if sample.name == name and sample.labels == labels
    ]


def test_metrics_endpoint_returns_prometheus_exposition() -> None:
    client = make_client()

    response = client.get("/metrics")
    families = list(text_string_to_metric_families(response.text))

    assert response.status_code == 200
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST
    assert families
    assert "rootlens_inventory_http_requests_total" in response.text
    assert "rootlens_inventory_http_request_duration_seconds" in response.text
    assert "rootlens_inventory_http_errors_total" in response.text
    assert "rootlens_inventory_reservations_total" in response.text


def test_health_increments_request_counter_and_duration_count() -> None:
    client = make_client()

    client.get("/health")
    exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_inventory_http_requests_total",
        {"method": "GET", "route": "/health", "status_code": "200"},
    ) == [1.0]
    assert sample_values(
        exposition,
        "rootlens_inventory_http_request_duration_seconds_count",
        {"method": "GET", "route": "/health"},
    ) == [1.0]


def test_handled_404_increments_bounded_error_counter() -> None:
    client = make_client()

    client.get("/does-not-exist")
    exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_inventory_http_errors_total",
        {"method": "GET", "route": "unmatched", "status_code": "404"},
    ) == [1.0]


def test_concrete_skus_share_item_route_label(monkeypatch: Any) -> None:
    async def missing_item(session: AsyncSession, sku: str) -> None:
        return None

    monkeypatch.setattr(inventory_items, "get_inventory_item_by_sku", missing_item)
    client = make_client()

    client.get("/items/LAPTOP-001")
    client.get("/items/PHONE-002")
    exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_inventory_http_requests_total",
        {"method": "GET", "route": "/items/{sku}", "status_code": "404"},
    ) == [2.0]
    assert "LAPTOP-001" not in exposition
    assert "PHONE-002" not in exposition


def test_reservation_uses_normalized_route_label(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        return inventory_items.InventoryReservationResult(sku, quantity, 6)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)
    client = make_client()

    client.post("/items/LAPTOP-001/reserve", json={"quantity": 1})
    exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_inventory_http_requests_total",
        {
            "method": "POST",
            "route": "/items/{sku}/reserve",
            "status_code": "200",
        },
    ) == [1.0]
    assert "LAPTOP-001" not in exposition


@pytest.mark.parametrize(
    ("error", "status_code", "outcome", "reason"),
    [
        (None, 200, "success", "none"),
        (
            inventory_items.InventoryItemNotFoundError,
            404,
            "rejected",
            "item_not_found",
        ),
        (
            inventory_items.InsufficientInventoryError,
            409,
            "rejected",
            "insufficient_inventory",
        ),
        (
            inventory_items.InventoryReservationDatabaseError,
            500,
            "error",
            "database_error",
        ),
    ],
)
def test_reservation_outcome_metric(
    monkeypatch: Any,
    error: type[Exception] | None,
    status_code: int,
    outcome: str,
    reason: str,
) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        if error is not None:
            raise error
        return inventory_items.InventoryReservationResult(sku, quantity, 6)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)
    client = make_client()

    response = client.post("/items/SKU-001/reserve", json={"quantity": 1})
    exposition = scrape(client)

    assert response.status_code == status_code
    assert sample_values(
        exposition,
        "rootlens_inventory_reservations_total",
        {"outcome": outcome, "reason": reason},
    ) == [1.0]


def test_metrics_scrape_does_not_count_itself() -> None:
    client = make_client()

    first_scrape = scrape(client)
    second_scrape = scrape(client)

    assert "rootlens_inventory_http_requests_total{" not in first_scrape
    assert "rootlens_inventory_http_requests_total{" not in second_scrape


def test_application_instances_have_isolated_registries() -> None:
    first_client = make_client()
    second_client = make_client()

    first_client.get("/health")

    assert "rootlens_inventory_http_requests_total{" in scrape(first_client)
    assert "rootlens_inventory_http_requests_total{" not in scrape(second_client)
