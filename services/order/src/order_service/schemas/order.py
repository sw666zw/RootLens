"""API schemas for transient orders."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

Sku = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class OrderCreate(BaseModel):
    """Values accepted when creating an order."""

    sku: Sku
    quantity: int = Field(gt=0, strict=True)


class OrderResponse(BaseModel):
    """Confirmed transient order returned by the API."""

    order_id: UUID
    sku: str
    quantity: int
    status: Literal["confirmed"]
    remaining_inventory: int
