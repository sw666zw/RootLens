"""Unit tests for Order-specific SQLAlchemy repository behavior."""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.models import Order
from order_service.repositories.orders import (
    OrderPersistenceError,
    change_order_status,
    create_pending_order,
    list_orders,
)


def mock_session() -> tuple[AsyncSession, Mock]:
    session = Mock(spec=AsyncSession)
    session.add = Mock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    return cast(AsyncSession, session), session


def test_create_pending_commits_and_refreshes() -> None:
    session, session_mock = mock_session()
    order_id = uuid4()

    result = asyncio.run(
        create_pending_order(
            session,
            order_id=order_id,
            sku="SKU-001",
            quantity=2,
            request_id="request-id",
            trace_id=None,
        )
    )

    assert result.id == order_id
    assert result.status == "pending"
    cast(Any, session_mock).add.assert_called_once_with(result)
    cast(Any, session_mock).commit.assert_awaited_once_with()
    cast(Any, session_mock).refresh.assert_awaited_once_with(result)


def test_create_pending_rolls_back_after_failure() -> None:
    session, session_mock = mock_session()
    cast(Any, session_mock).commit.side_effect = SQLAlchemyError("secret")

    with pytest.raises(OrderPersistenceError):
        asyncio.run(
            create_pending_order(
                session,
                order_id=uuid4(),
                sku="SKU-001",
                quantity=1,
                request_id="request-id",
                trace_id=None,
            )
        )

    cast(Any, session_mock).rollback.assert_awaited_once_with()
    cast(Any, session_mock).refresh.assert_not_awaited()


def test_change_status_uses_update_then_commits_and_refreshes() -> None:
    session, session_mock = mock_session()
    order = Order(
        id=uuid4(),
        sku="SKU-001",
        quantity=1,
        status="confirmed",
        request_id="request-id",
    )
    query_result = Mock()
    query_result.scalar_one_or_none.return_value = order
    cast(Any, session_mock).execute.return_value = query_result

    result = asyncio.run(
        change_order_status(
            session,
            order_id=order.id,
            status="confirmed",
            remaining_inventory=4,
            failure_reason=None,
        )
    )

    statement = cast(Any, session_mock).execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE orders")
    assert "orders.status =" in sql
    assert result is order
    cast(Any, session_mock).commit.assert_awaited_once_with()
    cast(Any, session_mock).refresh.assert_awaited_once_with(order)


def test_change_status_rolls_back_after_database_failure() -> None:
    session, session_mock = mock_session()
    cast(Any, session_mock).execute.side_effect = SQLAlchemyError("secret")

    with pytest.raises(OrderPersistenceError):
        asyncio.run(
            change_order_status(
                session,
                order_id=uuid4(),
                status="failed",
                remaining_inventory=None,
                failure_reason="inventory_unavailable",
            )
        )

    cast(Any, session_mock).rollback.assert_awaited_once_with()
    cast(Any, session_mock).commit.assert_not_awaited()


def test_list_orders_has_required_database_ordering() -> None:
    session, session_mock = mock_session()
    scalar_result = Mock()
    scalar_result.all.return_value = []
    query_result = Mock()
    query_result.scalars.return_value = scalar_result
    cast(Any, session_mock).execute.return_value = query_result

    assert asyncio.run(list_orders(session)) == []

    statement = cast(Any, session_mock).execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ORDER BY orders.created_at DESC, orders.id ASC" in sql
