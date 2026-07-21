import io
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient as FastAPITestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.database import get_database_session
from inventory_service.logging_config import configure_logging
from inventory_service.main import create_app
from inventory_service.repositories import inventory_items
from inventory_service.schemas import InventoryItemCreate, InventoryReservationRequest

TEST_TIME = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def make_item(
    sku: str = "LAPTOP-001",
    name: str = "Demo Laptop",
    quantity: int = 10,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        sku=sku,
        name=name,
        quantity=quantity,
        created_at=TEST_TIME,
        updated_at=TEST_TIME,
    )


def make_client() -> FastAPITestClient:
    application = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    application.dependency_overrides[get_database_session] = override_session
    return FastAPITestClient(application)


def assert_complete_item_response(payload: dict[str, Any]) -> None:
    assert set(payload) == {
        "id",
        "sku",
        "name",
        "quantity",
        "created_at",
        "updated_at",
    }
    UUID(payload["id"])
    assert datetime.fromisoformat(payload["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(payload["updated_at"]).tzinfo is not None


def test_create_item_returns_201_and_complete_response(monkeypatch: Any) -> None:
    async def create_item(
        session: AsyncSession,
        item_data: InventoryItemCreate,
    ) -> SimpleNamespace:
        return make_item(item_data.sku, item_data.name, item_data.quantity)

    monkeypatch.setattr(inventory_items, "create_inventory_item", create_item)

    response = make_client().post(
        "/items",
        json={"sku": "LAPTOP-001", "name": "Demo Laptop", "quantity": 10},
    )

    assert response.status_code == 201
    assert response.json()["sku"] == "LAPTOP-001"
    assert response.json()["name"] == "Demo Laptop"
    assert response.json()["quantity"] == 10
    assert_complete_item_response(response.json())


def test_create_item_defaults_quantity_to_zero(monkeypatch: Any) -> None:
    async def create_item(
        session: AsyncSession,
        item_data: InventoryItemCreate,
    ) -> SimpleNamespace:
        return make_item(item_data.sku, item_data.name, item_data.quantity)

    monkeypatch.setattr(inventory_items, "create_inventory_item", create_item)

    response = make_client().post(
        "/items",
        json={"sku": "LAPTOP-001", "name": "Demo Laptop"},
    )

    assert response.status_code == 201
    assert response.json()["quantity"] == 0


def test_create_item_strips_sku_and_name_whitespace(monkeypatch: Any) -> None:
    async def create_item(
        session: AsyncSession,
        item_data: InventoryItemCreate,
    ) -> SimpleNamespace:
        return make_item(item_data.sku, item_data.name, item_data.quantity)

    monkeypatch.setattr(inventory_items, "create_inventory_item", create_item)

    response = make_client().post(
        "/items",
        json={"sku": "  laptop-001  ", "name": "  Demo Laptop  "},
    )

    assert response.status_code == 201
    assert response.json()["sku"] == "laptop-001"
    assert response.json()["name"] == "Demo Laptop"


def test_create_item_rejects_negative_quantity() -> None:
    response = make_client().post(
        "/items",
        json={"sku": "LAPTOP-001", "name": "Demo Laptop", "quantity": -1},
    )

    assert response.status_code == 422


def test_create_item_rejects_empty_sku() -> None:
    response = make_client().post(
        "/items",
        json={"sku": "   ", "name": "Demo Laptop"},
    )

    assert response.status_code == 422


def test_create_item_rejects_empty_name() -> None:
    response = make_client().post(
        "/items",
        json={"sku": "LAPTOP-001", "name": "   "},
    )

    assert response.status_code == 422


def test_create_item_returns_exact_duplicate_sku_error(monkeypatch: Any) -> None:
    async def create_item(
        session: AsyncSession,
        item_data: InventoryItemCreate,
    ) -> SimpleNamespace:
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr(inventory_items, "create_inventory_item", create_item)

    response = make_client().post(
        "/items",
        json={"sku": "LAPTOP-001", "name": "Demo Laptop"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "An inventory item with this SKU already exists."
    }
    assert "duplicate" not in response.text


def test_list_items_returns_items_sorted_by_sku(monkeypatch: Any) -> None:
    async def list_items(session: AsyncSession) -> list[SimpleNamespace]:
        return [make_item("SKU-B", "Second"), make_item("SKU-A", "First")]

    monkeypatch.setattr(inventory_items, "list_inventory_items", list_items)

    response = make_client().get("/items")

    assert response.status_code == 200
    assert [item["sku"] for item in response.json()] == ["SKU-A", "SKU-B"]


def test_list_items_returns_empty_list(monkeypatch: Any) -> None:
    async def list_items(session: AsyncSession) -> list[SimpleNamespace]:
        return []

    monkeypatch.setattr(inventory_items, "list_inventory_items", list_items)

    response = make_client().get("/items")

    assert response.status_code == 200
    assert response.json() == []


def test_get_item_returns_match(monkeypatch: Any) -> None:
    async def get_item(
        session: AsyncSession,
        sku: str,
    ) -> SimpleNamespace:
        return make_item(sku, "Demo Laptop")

    monkeypatch.setattr(inventory_items, "get_inventory_item_by_sku", get_item)

    response = make_client().get("/items/LAPTOP-001")

    assert response.status_code == 200
    assert response.json()["sku"] == "LAPTOP-001"
    assert_complete_item_response(response.json())


def test_get_item_returns_exact_not_found_error(monkeypatch: Any) -> None:
    async def get_item(session: AsyncSession, sku: str) -> None:
        return None

    monkeypatch.setattr(inventory_items, "get_inventory_item_by_sku", get_item)

    response = make_client().get("/items/MISSING")

    assert response.status_code == 404
    assert response.json() == {"detail": "Inventory item not found."}


def test_item_response_has_request_id(monkeypatch: Any) -> None:
    async def list_items(session: AsyncSession) -> list[SimpleNamespace]:
        return []

    monkeypatch.setattr(inventory_items, "list_inventory_items", list_items)

    response = make_client().get(
        "/items",
        headers={"X-Request-ID": "items-request-id"},
    )

    assert response.headers["X-Request-ID"] == "items-request-id"


def successful_reservation(
    sku: str,
    quantity: int,
    remaining_quantity: int = 7,
) -> inventory_items.InventoryReservationResult:
    return inventory_items.InventoryReservationResult(
        sku=sku,
        reserved_quantity=quantity,
        remaining_quantity=remaining_quantity,
    )


def test_reservation_returns_200_with_exact_response_fields(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        return successful_reservation(sku, quantity)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)

    response = make_client().post(
        "/items/LAPTOP-001/reserve",
        json={"quantity": 3},
    )

    assert response.status_code == 200
    assert response.json() == {
        "sku": "LAPTOP-001",
        "reserved_quantity": 3,
        "remaining_quantity": 7,
    }


def test_reservation_of_complete_stock_returns_zero_remaining(
    monkeypatch: Any,
) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        return successful_reservation(sku, quantity, remaining_quantity=0)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)

    response = make_client().post(
        "/items/LAPTOP-001/reserve",
        json={"quantity": 10},
    )

    assert response.status_code == 200
    assert response.json()["remaining_quantity"] == 0


@pytest.mark.parametrize("quantity", [0, -1, True])
def test_reservation_rejects_invalid_quantities(quantity: object) -> None:
    response = make_client().post(
        "/items/LAPTOP-001/reserve",
        json={"quantity": quantity},
    )

    assert response.status_code == 422


def test_reservation_schema_rejects_boolean_quantity() -> None:
    with pytest.raises(ValueError):
        InventoryReservationRequest(quantity=True)


def test_reservation_returns_exact_not_found_response(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        raise inventory_items.InventoryItemNotFoundError

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)

    response = make_client().post(
        "/items/MISSING/reserve",
        json={"quantity": 1},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Inventory item not found."}


def test_reservation_returns_exact_insufficient_response(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        raise inventory_items.InsufficientInventoryError

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)

    response = make_client().post(
        "/items/LAPTOP-001/reserve",
        json={"quantity": 11},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Insufficient inventory available."}


def test_reservation_response_contains_generated_request_id(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        return successful_reservation(sku, quantity)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)

    response = make_client().post(
        "/items/LAPTOP-001/reserve",
        json={"quantity": 1},
    )

    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id


def test_reservation_preserves_supplied_request_id(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        return successful_reservation(sku, quantity)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)

    response = make_client().post(
        "/items/LAPTOP-001/reserve",
        headers={"X-Request-ID": "reservation-id"},
        json={"quantity": 1},
    )

    assert response.headers["X-Request-ID"] == "reservation-id"


def test_reservation_database_error_returns_generic_response(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        raise inventory_items.InventoryReservationDatabaseError from SQLAlchemyError(
            "postgresql+asyncpg://user:secret@database.internal/inventory"
        )

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)

    response = make_client().post(
        "/items/LAPTOP-001/reserve",
        json={"quantity": 1},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to reserve inventory."}
    assert "secret" not in response.text
    assert "postgresql+asyncpg://" not in response.text


def test_reservation_success_log_contains_domain_fields(
    monkeypatch: Any,
) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        return successful_reservation(sku, quantity)

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)
    output = io.StringIO()
    configure_logging(output)

    make_client().post(
        "/items/LAPTOP-001/reserve",
        headers={"X-Request-ID": "reservation-log-id"},
        json={"quantity": 3},
    )

    logs = [json.loads(line) for line in output.getvalue().splitlines()]
    payload = next(
        log for log in logs if log["message"] == "inventory_reservation_succeeded"
    )
    assert payload["level"] == "INFO"
    assert payload["service"] == "inventory"
    assert payload["request_id"] == "reservation-log-id"
    assert payload["sku"] == "LAPTOP-001"
    assert payload["requested_quantity"] == 3
    assert payload["remaining_quantity"] == 7


def test_reservation_rejection_log_contains_reason(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        raise inventory_items.InsufficientInventoryError

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)
    output = io.StringIO()
    configure_logging(output)

    make_client().post(
        "/items/LAPTOP-001/reserve",
        headers={"X-Request-ID": "rejection-log-id"},
        json={"quantity": 11},
    )

    logs = [json.loads(line) for line in output.getvalue().splitlines()]
    payload = next(
        log for log in logs if log["message"] == "inventory_reservation_rejected"
    )
    assert payload["level"] == "WARNING"
    assert payload["service"] == "inventory"
    assert payload["request_id"] == "rejection-log-id"
    assert payload["sku"] == "LAPTOP-001"
    assert payload["requested_quantity"] == 11
    assert payload["reason"] == "insufficient_inventory"


def test_missing_reservation_log_contains_not_found_reason(monkeypatch: Any) -> None:
    async def reserve_item(
        session: AsyncSession,
        sku: str,
        quantity: int,
    ) -> inventory_items.InventoryReservationResult:
        raise inventory_items.InventoryItemNotFoundError

    monkeypatch.setattr(inventory_items, "reserve_inventory_item", reserve_item)
    output = io.StringIO()
    configure_logging(output)

    make_client().post(
        "/items/MISSING/reserve",
        headers={"X-Request-ID": "missing-log-id"},
        json={"quantity": 1},
    )

    logs = [json.loads(line) for line in output.getvalue().splitlines()]
    payload = next(
        log for log in logs if log["message"] == "inventory_reservation_rejected"
    )
    assert payload["level"] == "WARNING"
    assert payload["request_id"] == "missing-log-id"
    assert payload["sku"] == "MISSING"
    assert payload["requested_quantity"] == 1
    assert payload["reason"] == "item_not_found"
