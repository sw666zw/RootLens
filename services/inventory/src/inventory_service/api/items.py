"""Create and read endpoints for inventory items."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.database import get_database_session
from inventory_service.repositories import inventory_items
from inventory_service.schemas import InventoryItemCreate, InventoryItemRead

router = APIRouter(prefix="/items", tags=["items"])


@router.post(
    "",
    response_model=InventoryItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    item_data: InventoryItemCreate,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> InventoryItemRead:
    """Create one inventory item."""
    try:
        item = await inventory_items.create_inventory_item(session, item_data)
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An inventory item with this SKU already exists.",
        ) from error
    return InventoryItemRead.model_validate(item)


@router.get("", response_model=list[InventoryItemRead])
async def list_items(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[InventoryItemRead]:
    """List all inventory items in ascending SKU order."""
    items = await inventory_items.list_inventory_items(session)
    return [
        InventoryItemRead.model_validate(item)
        for item in sorted(items, key=lambda item: item.sku)
    ]


@router.get("/{sku}", response_model=InventoryItemRead)
async def get_item(
    sku: str,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> InventoryItemRead:
    """Retrieve one inventory item by its exact SKU."""
    item = await inventory_items.get_inventory_item_by_sku(session, sku)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory item not found.",
        )
    return InventoryItemRead.model_validate(item)
