"""Downstream clients used by the Order Service."""

from order_service.clients.inventory import (
    InsufficientInventoryError,
    InventoryClient,
    InventoryInvalidResponseError,
    InventoryItemNotFoundError,
    InventoryMalformedResponseError,
    InventoryUnavailableError,
)

__all__ = [
    "InventoryClient",
    "InventoryInvalidResponseError",
    "InventoryItemNotFoundError",
    "InventoryMalformedResponseError",
    "InventoryUnavailableError",
    "InsufficientInventoryError",
]
