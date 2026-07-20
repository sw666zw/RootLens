"""API schemas for inventory items."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sku = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ItemName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class InventoryItemCreate(BaseModel):
    """Values accepted when creating an inventory item."""

    sku: Sku
    name: ItemName
    quantity: int = Field(default=0, ge=0, strict=True)


class InventoryItemRead(BaseModel):
    """Complete inventory item returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    quantity: int
    created_at: datetime
    updated_at: datetime
