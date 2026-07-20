"""Create the inventory_items table.

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
    """Create the inventory_items table and SKU index."""
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "quantity >= 0",
            name="ck_inventory_items_quantity_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_inventory_items_sku"),
    )
    op.create_index("ix_inventory_items_sku", "inventory_items", ["sku"])


def downgrade() -> None:
    """Remove the inventory_items table."""
    op.drop_index("ix_inventory_items_sku", table_name="inventory_items")
    op.drop_table("inventory_items")
