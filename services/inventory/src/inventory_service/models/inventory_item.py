"""Persistent inventory item model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from inventory_service.models.base import Base


class InventoryItem(Base):
    """A uniquely identified product and its current on-hand quantity."""

    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 0",
            name="ck_inventory_items_quantity_nonnegative",
        ),
        UniqueConstraint("sku", name="uq_inventory_items_sku"),
        Index("ix_inventory_items_sku", "sku"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
