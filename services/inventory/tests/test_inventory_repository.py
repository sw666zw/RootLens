import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.repositories.inventory_items import create_inventory_item
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
