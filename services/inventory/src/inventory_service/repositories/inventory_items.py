"""Database operations specific to inventory items."""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.models import InventoryItem
from inventory_service.schemas import InventoryItemCreate


async def create_inventory_item(
    session: AsyncSession,
    item_data: InventoryItemCreate,
) -> InventoryItem:
    """Persist a new inventory item and return its refreshed model."""
    item = InventoryItem(**item_data.model_dump())
    session.add(item)
    try:
        await session.commit()
        await session.refresh(item)
    except SQLAlchemyError:
        await session.rollback()
        raise
    return item


async def list_inventory_items(session: AsyncSession) -> list[InventoryItem]:
    """Return every inventory item ordered by SKU."""
    result = await session.execute(select(InventoryItem).order_by(InventoryItem.sku))
    return list(result.scalars().all())


async def get_inventory_item_by_sku(
    session: AsyncSession,
    sku: str,
) -> InventoryItem | None:
    """Return the inventory item with the exact SKU, if it exists."""
    result = await session.execute(
        select(InventoryItem).where(InventoryItem.sku == sku)
    )
    return result.scalar_one_or_none()
