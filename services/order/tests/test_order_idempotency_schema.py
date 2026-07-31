"""Order idempotency model and migration contract tests."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

from sqlalchemy import CheckConstraint, Index

from order_service.models import Order


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0002_add_order_idempotency.py"
    )
    spec = importlib.util.spec_from_file_location("order_migration_0002", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_has_paired_check_and_partial_unique_index() -> None:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in Order.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {index.name: index for index in Order.__table__.indexes}

    assert "ck_orders_idempotency_fields_paired" in constraints
    assert "ck_orders_request_fingerprint_format" in constraints
    index = indexes["uq_orders_idempotency_key_not_null"]
    assert isinstance(index, Index)
    assert index.unique is True
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "idempotency_key IS NOT NULL"
    )


def test_migration_upgrade_and_downgrade_include_partial_unique_index() -> None:
    migration = load_migration()
    operation = Mock()
    migration.op = operation

    migration.upgrade()
    create_index = operation.create_index
    create_index.assert_called_once()
    assert create_index.call_args.args[:3] == (
        "uq_orders_idempotency_key_not_null",
        "orders",
        ["idempotency_key"],
    )
    assert create_index.call_args.kwargs["unique"] is True
    assert str(create_index.call_args.kwargs["postgresql_where"]) == (
        "idempotency_key IS NOT NULL"
    )

    migration.downgrade()
    operation.drop_index.assert_called_once_with(
        "uq_orders_idempotency_key_not_null",
        table_name="orders",
    )
