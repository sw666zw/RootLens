"""Database operations specific to inventory items."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.models import InventoryItem
from inventory_service.schemas import InventoryItemCreate


class InventoryReservationError(Exception):
    """Base class for inventory reservation failures."""


class InventoryItemNotFoundError(InventoryReservationError):
    """Raised when a reservation targets an unknown SKU."""


class InsufficientInventoryError(InventoryReservationError):
    """Raised when a reservation exceeds the available quantity."""


class InventoryReservationDatabaseError(InventoryReservationError):
    """Raised when the database cannot complete a reservation."""


@dataclass(frozen=True)
class InventoryReservationResult:
    """Inventory values produced by a successful reservation."""

    sku: str
    reserved_quantity: int
    remaining_quantity: int


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


async def reserve_inventory_item(
    session: AsyncSession,
    sku: str,
    requested_quantity: int,
) -> InventoryReservationResult:
    """Reserve quantity under a row lock in one database transaction."""
    try:
        result = await session.execute(
            select(InventoryItem).where(InventoryItem.sku == sku).with_for_update()
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise InventoryItemNotFoundError
        if item.quantity < requested_quantity:
            raise InsufficientInventoryError

        item.quantity -= requested_quantity
        item.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(item)
    except (InventoryItemNotFoundError, InsufficientInventoryError):
        await session.rollback()
        raise
    except SQLAlchemyError as error:
        await session.rollback()
        raise InventoryReservationDatabaseError from error

    return InventoryReservationResult(
        sku=item.sku,
        reserved_quantity=requested_quantity,
        remaining_quantity=item.quantity,
    )
