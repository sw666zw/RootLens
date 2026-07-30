"""Test doubles and Prometheus helpers."""

import json
from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient as FastAPITestClient
from prometheus_client.parser import text_string_to_metric_families

from order_service.config import Settings
from order_service.main import create_app
from order_service.tracing import TracingConfiguration

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(
    handler: Handler,
    tracing: TracingConfiguration | None = None,
) -> FastAPITestClient:
    """Create an app whose only downstream transport is in memory."""

    def client_factory(_: Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://inventory.test",
            timeout=5.0,
            transport=httpx.MockTransport(handler),
        )

    return FastAPITestClient(
        create_app(tracing=tracing, http_client_factory=client_factory)
    )


def successful_inventory(request: httpx.Request) -> httpx.Response:
    """Return a valid reservation response matching the request."""
    quantity = json.loads(request.content)["quantity"]
    sku = request.url.path.split("/")[2]
    return httpx.Response(
        200,
        json={
            "sku": sku,
            "reserved_quantity": quantity,
            "remaining_quantity": 8,
        },
    )


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
