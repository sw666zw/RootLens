"""Shared test environment for the Order Service."""

import os

os.environ["OTEL_TRACES_ENABLED"] = "false"
os.environ["ROOTLENS_FILE_LOGGING_ENABLED"] = "false"
os.environ["INVENTORY_SERVICE_URL"] = "http://inventory.test"
os.environ["ORDER_DATABASE_URL"] = (
    "postgresql+asyncpg://rootlens_order:test_password@localhost:5433/"
    "rootlens_orders_test"
)
