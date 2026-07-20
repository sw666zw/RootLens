"""Database models and shared metadata for the Inventory Service."""

from inventory_service.models.base import Base
from inventory_service.models.inventory_item import InventoryItem

__all__ = ["Base", "InventoryItem"]
