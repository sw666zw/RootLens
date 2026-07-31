"""Order creation and downstream translation tests."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from test_support.order import InMemoryOrdersRepository, make_client

from order_service.repositories import orders


class FailingPendingRepository(InMemoryOrdersRepository):
    async def create_pending(self, *args: Any, **kwargs: Any) -> None:
        raise orders.OrderPersistenceError


class FailingFinalRepository(InMemoryOrdersRepository):
    async def change_status(self, *args: Any, **kwargs: Any) -> None:
        raise orders.OrderPersistenceError


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


def test_pending_is_stored_before_inventory_call() -> None:
    repository = InMemoryOrdersRepository()

    def handler(_: httpx.Request) -> httpx.Response:
        assert repository.events == [("persist", "pending")]
        return httpx.Response(
            200,
            json={
                "sku": "SKU-001",
                "reserved_quantity": 1,
                "remaining_quantity": 4,
            },
        )

    with make_client(handler, repository=repository) as client:
        response = client.post(
            "/orders",
            json={"sku": "SKU-001", "quantity": 1},
        )

    assert response.status_code == 201
    assert repository.events == [
        ("persist", "pending"),
        ("persist", "confirmed"),
    ]


def test_inventory_is_not_called_when_pending_persistence_fails() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("Inventory must not be called.")

    with make_client(handler, repository=FailingPendingRepository()) as client:
        response = client.post(
            "/orders",
            json={"sku": "SKU-001", "quantity": 1},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Order service unavailable."}
    assert calls == 0


def test_final_persistence_failure_does_not_repeat_inventory_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "sku": "SKU-001",
                "reserved_quantity": 1,
                "remaining_quantity": 3,
            },
        )

    with make_client(handler, repository=FailingFinalRepository()) as client:
        response = client.post(
            "/orders",
            json={"sku": "SKU-001", "quantity": 1},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Order service unavailable."}
    assert calls == 1


@pytest.mark.parametrize(
    ("inventory_status", "order_status", "body"),
    [
        (404, 404, {"detail": "Inventory item not found."}),
        (409, 409, {"detail": "Insufficient inventory available."}),
        (
            422,
            503,
            {"detail": "Inventory service unavailable."},
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


@pytest.mark.parametrize(
    ("inventory_status", "stored_status", "failure_reason"),
    [
        (404, "rejected", "item_not_found"),
        (409, "rejected", "insufficient_inventory"),
        (500, "failed", "inventory_unavailable"),
        (422, "failed", "inventory_invalid_response"),
    ],
)
def test_downstream_outcome_is_persisted(
    inventory_status: int,
    stored_status: str,
    failure_reason: str,
) -> None:
    repository = InMemoryOrdersRepository()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(inventory_status)

    with make_client(handler, repository=repository) as client:
        client.post("/orders", json={"sku": "SKU-001", "quantity": 1})

    persisted = next(iter(repository.orders.values()))
    assert persisted.status == stored_status
    assert persisted.failure_reason == failure_reason


def persisted_order(
    order_id: UUID,
    *,
    created_at: datetime,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        sku="SKU-001",
        quantity=1,
        status="confirmed",
        remaining_inventory=4,
        failure_reason=None,
        request_id="read-request",
        trace_id=None,
        created_at=created_at,
        updated_at=created_at,
    )


def test_list_orders_returns_empty_list() -> None:
    with make_client(lambda _: httpx.Response(500)) as client:
        response = client.get("/orders")

    assert response.status_code == 200
    assert response.json() == []


def test_list_orders_uses_deterministic_ordering() -> None:
    repository = InMemoryOrdersRepository()
    now = datetime.now(UTC)
    newest_low_id = UUID("00000000-0000-0000-0000-000000000001")
    newest_high_id = UUID("00000000-0000-0000-0000-000000000002")
    older_id = UUID("00000000-0000-0000-0000-000000000003")
    repository.orders = {
        older_id: persisted_order(older_id, created_at=now - timedelta(seconds=1)),
        newest_high_id: persisted_order(newest_high_id, created_at=now),
        newest_low_id: persisted_order(newest_low_id, created_at=now),
    }

    with make_client(
        lambda _: httpx.Response(500),
        repository=repository,
    ) as client:
        response = client.get("/orders")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        str(newest_low_id),
        str(newest_high_id),
        str(older_id),
    ]


def test_get_order_returns_match_and_missing_is_exact() -> None:
    repository = InMemoryOrdersRepository()
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    repository.orders[order_id] = persisted_order(
        order_id,
        created_at=datetime.now(UTC),
    )

    with make_client(
        lambda _: httpx.Response(500),
        repository=repository,
    ) as client:
        found = client.get(f"/orders/{order_id}")
        missing = client.get("/orders/00000000-0000-0000-0000-000000000002")

    assert found.status_code == 200
    assert found.json()["id"] == str(order_id)
    assert set(found.json()) == {
        "id",
        "sku",
        "quantity",
        "status",
        "remaining_inventory",
        "failure_reason",
        "request_id",
        "trace_id",
        "created_at",
        "updated_at",
    }
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Order not found."}
