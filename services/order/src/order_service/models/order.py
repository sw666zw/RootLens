"""Persistent order-attempt model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from order_service.models.base import Base


class Order(Base):
    """A durable record of an Order creation attempt and its outcome."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected', 'failed')",
            name="ck_orders_status_allowed",
        ),
        CheckConstraint(
            "remaining_inventory IS NULL OR remaining_inventory >= 0",
            name="ck_orders_remaining_inventory_nonnegative",
        ),
        CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN "
            "('item_not_found', 'insufficient_inventory', "
            "'inventory_unavailable', 'inventory_invalid_response', "
            "'order_persistence_failure')",
            name="ck_orders_failure_reason_allowed",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    remaining_inventory: Mapped[int | None] = mapped_column(nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
