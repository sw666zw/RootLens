"""Order Service request and response schemas."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sku = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class OrderCreate(BaseModel):
    """Values accepted when creating an order."""

    sku: Sku
    quantity: int = Field(gt=0, strict=True)


class OrderResponse(BaseModel):
    """Confirmed order returned by the creation endpoint."""

    order_id: UUID
    sku: str
    quantity: int
    status: Literal["confirmed"]
    remaining_inventory: int


class PersistedOrderResponse(BaseModel):
    """Complete persisted order returned by read endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    quantity: int
    status: Literal["pending", "confirmed", "rejected", "failed"]
    remaining_inventory: int | None
    failure_reason: (
        Literal[
            "item_not_found",
            "insufficient_inventory",
            "inventory_unavailable",
            "inventory_invalid_response",
            "order_persistence_failure",
        ]
        | None
    )
    request_id: str
    trace_id: str | None
    created_at: datetime
    updated_at: datetime
