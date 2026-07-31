"""Prometheus metric tests."""

import httpx
import pytest
from test_support.order import (
    InMemoryOrdersRepository,
    make_client,
    sample_values,
    scrape,
    successful_inventory,
)

from order_service.repositories import orders


class FailingFinalRepository(InMemoryOrdersRepository):
    async def change_status(self, *args: object, **kwargs: object) -> None:
        raise orders.OrderPersistenceError


def test_metrics_endpoint_and_self_exclusion() -> None:
    with make_client(successful_inventory) as client:
        first = scrape(client)
        second = scrape(client)

    assert "rootlens_order_http_requests_total{" not in first
    assert "rootlens_order_http_requests_total{" not in second
    assert "rootlens_order_creations_total" in first


@pytest.mark.parametrize(
    ("status_code", "labels"),
    [
        (200, {"outcome": "confirmed", "reason": "none"}),
        (404, {"outcome": "rejected", "reason": "item_not_found"}),
        (409, {"outcome": "rejected", "reason": "insufficient_inventory"}),
        (500, {"outcome": "error", "reason": "inventory_unavailable"}),
        (422, {"outcome": "error", "reason": "inventory_invalid_response"}),
    ],
)
def test_every_creation_outcome_increments_metric(
    status_code: int,
    labels: dict[str, str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code == 200:
            return successful_inventory(request)
        return httpx.Response(status_code)

    with make_client(handler) as client:
        client.post("/orders", json={"sku": "SKU-001", "quantity": 1})
        exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_order_creations_total",
        labels,
    ) == [1.0]
    assert sample_values(
        exposition,
        "rootlens_order_http_requests_total",
        {
            "method": "POST",
            "route": "/orders",
            "status_code": str(
                {200: 201, 404: 404, 409: 409, 500: 503, 422: 503}[status_code]
            ),
        },
    ) == [1.0]


def test_application_instances_have_isolated_registries() -> None:
    with make_client(successful_inventory) as first:
        first.get("/health")
        first_metrics = scrape(first)
    with make_client(successful_inventory) as second:
        second_metrics = scrape(second)

    assert "rootlens_order_http_requests_total{" in first_metrics
    assert "rootlens_order_http_requests_total{" not in second_metrics


def test_status_transition_metrics_follow_successful_commits() -> None:
    with make_client(successful_inventory) as client:
        client.post("/orders", json={"sku": "SKU-001", "quantity": 1})
        exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_order_status_transitions_total",
        {"from_status": "none", "to_status": "pending"},
    ) == [1.0]
    assert sample_values(
        exposition,
        "rootlens_order_status_transitions_total",
        {"from_status": "pending", "to_status": "confirmed"},
    ) == [1.0]


def test_failed_final_commit_does_not_increment_confirmed_transition() -> None:
    with make_client(
        successful_inventory,
        repository=FailingFinalRepository(),
    ) as client:
        client.post("/orders", json={"sku": "SKU-001", "quantity": 1})
        exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_order_status_transitions_total",
        {"from_status": "none", "to_status": "pending"},
    ) == [1.0]
    assert (
        sample_values(
            exposition,
            "rootlens_order_status_transitions_total",
            {"from_status": "pending", "to_status": "confirmed"},
        )
        == []
    )
