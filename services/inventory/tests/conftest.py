"""Shared test configuration for the Inventory Service."""

import os

os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://rootlens:test_password@localhost:5432/rootlens_inventory_test"
)
