"""Create the orders table.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable order-attempt table."""
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("remaining_inventory", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected', 'failed')",
            name="ck_orders_status_allowed",
        ),
        sa.CheckConstraint(
            "remaining_inventory IS NULL OR remaining_inventory >= 0",
            name="ck_orders_remaining_inventory_nonnegative",
        ),
        sa.CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN "
            "('item_not_found', 'insufficient_inventory', "
            "'inventory_unavailable', 'inventory_invalid_response', "
            "'order_persistence_failure')",
            name="ck_orders_failure_reason_allowed",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Remove the orders table."""
    op.drop_table("orders")
