"""Add idempotency claims to orders.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add paired idempotency fields and the atomic claim index."""
    op.add_column(
        "orders",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_orders_idempotency_fields_paired",
        "orders",
        "(idempotency_key IS NULL) = (request_fingerprint IS NULL)",
    )
    op.create_check_constraint(
        "ck_orders_request_fingerprint_format",
        "orders",
        "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_index(
        "uq_orders_idempotency_key_not_null",
        "orders",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove the idempotency claim schema safely."""
    op.drop_index("uq_orders_idempotency_key_not_null", table_name="orders")
    op.drop_constraint(
        "ck_orders_request_fingerprint_format",
        "orders",
        type_="check",
    )
    op.drop_constraint(
        "ck_orders_idempotency_fields_paired",
        "orders",
        type_="check",
    )
    op.drop_column("orders", "request_fingerprint")
    op.drop_column("orders", "idempotency_key")
