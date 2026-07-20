"""Pydantic request and response schemas."""

from inventory_service.schemas.inventory_item import (
    InventoryItemCreate,
    InventoryItemRead,
)

__all__ = ["InventoryItemCreate", "InventoryItemRead"]
