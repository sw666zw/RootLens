import asyncio
from datetime import UTC
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.models import InventoryItem
from inventory_service.repositories.inventory_items import (
    InsufficientInventoryError,
    InventoryItemNotFoundError,
    InventoryReservationDatabaseError,
    create_inventory_item,
    reserve_inventory_item,
)
from inventory_service.schemas import InventoryItemCreate


def test_create_inventory_item_rolls_back_after_database_failure() -> None:
    session = Mock(spec=AsyncSession)
    session.commit = AsyncMock(side_effect=SQLAlchemyError("database unavailable"))
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()

    async def create() -> None:
        await create_inventory_item(
            cast(AsyncSession, session),
            InventoryItemCreate(sku="SKU-001", name="Test item"),
        )

    try:
        asyncio.run(create())
    except SQLAlchemyError:
        pass
    else:
        raise AssertionError("Expected database failure")

    cast(Any, session).rollback.assert_awaited_once_with()
    cast(Any, session).refresh.assert_not_awaited()


def make_reservation_session(
    item: InventoryItem | None,
) -> tuple[AsyncSession, Mock]:
    result = Mock()
    result.scalar_one_or_none.return_value = item
    session = Mock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    return cast(AsyncSession, session), session


def test_reservation_uses_row_lock_and_commits_updated_item() -> None:
    item = InventoryItem(sku="SKU-001", name="Test item", quantity=5)
    session, session_mock = make_reservation_session(item)

    result = asyncio.run(reserve_inventory_item(session, "SKU-001", 2))

    statement = cast(Any, session_mock).execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert item.quantity == 3
    assert item.updated_at.tzinfo == UTC
    assert result.sku == "SKU-001"
    assert result.reserved_quantity == 2
    assert result.remaining_quantity == 3
    cast(Any, session_mock).commit.assert_awaited_once_with()
    cast(Any, session_mock).refresh.assert_awaited_once_with(item)
    cast(Any, session_mock).rollback.assert_not_awaited()


def test_reservation_of_complete_stock_leaves_zero() -> None:
    item = InventoryItem(sku="SKU-001", name="Test item", quantity=3)
    session, _ = make_reservation_session(item)

    result = asyncio.run(reserve_inventory_item(session, "SKU-001", 3))

    assert item.quantity == 0
    assert result.remaining_quantity == 0


def test_missing_reservation_rolls_back() -> None:
    session, session_mock = make_reservation_session(None)

    with pytest.raises(InventoryItemNotFoundError):
        asyncio.run(reserve_inventory_item(session, "MISSING", 1))

    cast(Any, session_mock).rollback.assert_awaited_once_with()
    cast(Any, session_mock).commit.assert_not_awaited()
    cast(Any, session_mock).refresh.assert_not_awaited()


def test_insufficient_reservation_rolls_back() -> None:
    item = InventoryItem(sku="SKU-001", name="Test item", quantity=1)
    session, session_mock = make_reservation_session(item)

    with pytest.raises(InsufficientInventoryError):
        asyncio.run(reserve_inventory_item(session, "SKU-001", 2))

    assert item.quantity == 1
    cast(Any, session_mock).rollback.assert_awaited_once_with()
    cast(Any, session_mock).commit.assert_not_awaited()
    cast(Any, session_mock).refresh.assert_not_awaited()


def test_reservation_database_failure_rolls_back_and_is_wrapped() -> None:
    session, session_mock = make_reservation_session(None)
    cast(Any, session_mock).execute.side_effect = SQLAlchemyError(
        "postgresql+asyncpg://user:secret@database.internal/inventory"
    )

    with pytest.raises(InventoryReservationDatabaseError):
        asyncio.run(reserve_inventory_item(session, "SKU-001", 1))

    cast(Any, session_mock).rollback.assert_awaited_once_with()
    cast(Any, session_mock).commit.assert_not_awaited()
    cast(Any, session_mock).refresh.assert_not_awaited()
