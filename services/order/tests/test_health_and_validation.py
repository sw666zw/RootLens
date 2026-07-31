"""Health, request ID, and input validation tests."""

from uuid import UUID

import pytest
from fastapi import Request
from test_support.order import make_client, successful_inventory

from order_service.database import check_database_readiness


def test_health_returns_exact_response_without_calling_inventory() -> None:
    calls = 0

    def fail_if_called(request: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("Inventory must not be called by health.")

    with make_client(fail_if_called) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "order"}
    assert calls == 0


def test_health_generates_uuid_request_id() -> None:
    with make_client(successful_inventory) as client:
        response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id


def test_health_preserves_non_empty_request_id() -> None:
    with make_client(successful_inventory) as client:
        response = client.get("/health", headers={"X-Request-ID": " caller-id "})

    assert response.headers["X-Request-ID"] == " caller-id "


async def database_is_ready(request: Request) -> bool:
    del request
    return True


async def database_is_unavailable(request: Request) -> bool:
    del request
    return False


def test_readiness_returns_exact_ready_response() -> None:
    with make_client(successful_inventory) as client:
        client.app.dependency_overrides[check_database_readiness] = database_is_ready
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "order",
        "database": "ok",
    }


def test_readiness_returns_exact_unavailable_response() -> None:
    with make_client(successful_inventory) as client:
        client.app.dependency_overrides[check_database_readiness] = (
            database_is_unavailable
        )
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "order",
        "database": "unavailable",
    }


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, "2"])
def test_invalid_quantities_return_422(quantity: object) -> None:
    with make_client(successful_inventory) as client:
        response = client.post(
            "/orders",
            json={"sku": "LAPTOP-001", "quantity": quantity},
        )

    assert response.status_code == 422
