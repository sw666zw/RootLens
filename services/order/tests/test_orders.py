"""Order creation and downstream translation tests."""

import json
from uuid import UUID

import httpx
import pytest

from helpers import make_client


def test_valid_order_returns_exact_fields_and_propagates_request_id() -> None:
    seen_request_id: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request_id
        seen_request_id = request.headers["X-Request-ID"]
        assert request.url.path == "/items/LAPTOP-001/reserve"
        assert json.loads(request.content) == {"quantity": 2}
        return httpx.Response(
            200,
            json={
                "sku": "LAPTOP-001",
                "reserved_quantity": 2,
                "remaining_quantity": 8,
            },
        )

    with make_client(handler) as client:
        response = client.post(
            "/orders",
            headers={"X-Request-ID": "distributed-request"},
            json={"sku": "  LAPTOP-001  ", "quantity": 2},
        )

    assert response.status_code == 201
    assert set(response.json()) == {
        "order_id",
        "sku",
        "quantity",
        "status",
        "remaining_inventory",
    }
    assert str(UUID(response.json()["order_id"])) == response.json()["order_id"]
    assert response.json()["sku"] == "LAPTOP-001"
    assert response.json()["quantity"] == 2
    assert response.json()["status"] == "confirmed"
    assert response.json()["remaining_inventory"] == 8
    assert seen_request_id == "distributed-request"
    assert response.headers["X-Request-ID"] == "distributed-request"


@pytest.mark.parametrize(
    ("inventory_status", "order_status", "body"),
    [
        (404, 404, {"detail": "Inventory item not found."}),
        (409, 409, {"detail": "Insufficient inventory available."}),
        (
            422,
            502,
            {"detail": "Inventory service returned an invalid response."},
        ),
        (500, 503, {"detail": "Inventory service unavailable."}),
        (599, 503, {"detail": "Inventory service unavailable."}),
    ],
)
def test_inventory_status_is_safely_translated(
    inventory_status: int,
    order_status: int,
    body: dict[str, str],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(inventory_status, text="downstream secret body")

    with make_client(handler) as client:
        response = client.post(
            "/orders",
            json={"sku": "LAPTOP-001", "quantity": 2},
        )

    assert response.status_code == order_status
    assert response.json() == body
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "exception_type",
    [
        httpx.ConnectError,
        httpx.ReadTimeout,
    ],
)
def test_network_failure_returns_safe_503(
    exception_type: type[httpx.RequestError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("credential-bearing internal URL", request=request)

    with make_client(handler) as client:
        response = client.post(
            "/orders",
            json={"sku": "LAPTOP-001", "quantity": 1},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Inventory service unavailable."}
    assert "credential" not in response.text


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"remaining_quantity": 8}),
        httpx.Response(
            200,
            json={
                "sku": "WRONG",
                "reserved_quantity": 2,
                "remaining_quantity": 8,
            },
        ),
    ],
)
def test_malformed_success_returns_safe_503(response: httpx.Response) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return response

    with make_client(handler) as client:
        result = client.post(
            "/orders",
            json={"sku": "LAPTOP-001", "quantity": 2},
        )

    assert result.status_code == 503
    assert result.json() == {"detail": "Inventory service unavailable."}
