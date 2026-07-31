"""Database operations specific to persisted orders."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.models import Order


class OrderPersistenceError(Exception):
    """Raised when the Order database cannot complete an operation."""


class PersistedOrderNotFoundError(Exception):
    """Raised when an expected persisted order no longer exists."""


async def create_pending_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    sku: str,
    quantity: int,
    request_id: str,
    trace_id: str | None,
) -> Order:
    """Commit and return a new pending order."""
    order = Order(
        id=order_id,
        sku=sku,
        quantity=quantity,
        status="pending",
        remaining_inventory=None,
        failure_reason=None,
        request_id=request_id,
        trace_id=trace_id,
    )
    session.add(order)
    try:
        await session.commit()
        await session.refresh(order)
    except SQLAlchemyError as error:
        await session.rollback()
        raise OrderPersistenceError from error
    return order


async def change_order_status(
    session: AsyncSession,
    *,
    order_id: UUID,
    status: str,
    remaining_inventory: int | None,
    failure_reason: str | None,
) -> Order:
    """Commit one durable transition from pending to a terminal status."""
    statement = (
        update(Order)
        .where(Order.id == order_id, Order.status == "pending")
        .values(
            status=status,
            remaining_inventory=remaining_inventory,
            failure_reason=failure_reason,
            updated_at=datetime.now(UTC),
        )
        .returning(Order)
    )
    try:
        result = await session.execute(statement)
        order = result.scalar_one_or_none()
        if order is None:
            await session.rollback()
            raise PersistedOrderNotFoundError
        await session.commit()
        await session.refresh(order)
    except PersistedOrderNotFoundError:
        raise
    except SQLAlchemyError as error:
        await session.rollback()
        raise OrderPersistenceError from error
    return order


async def get_order_by_id(
    session: AsyncSession,
    order_id: UUID,
) -> Order | None:
    """Return one persisted order by UUID."""
    try:
        result = await session.execute(select(Order).where(Order.id == order_id))
    except SQLAlchemyError as error:
        await session.rollback()
        raise OrderPersistenceError from error
    return result.scalar_one_or_none()


async def list_orders(session: AsyncSession) -> list[Order]:
    """List orders newest first with a stable UUID tie-breaker."""
    statement = select(Order).order_by(Order.created_at.desc(), Order.id.asc())
    try:
        result = await session.execute(statement)
    except SQLAlchemyError as error:
        await session.rollback()
        raise OrderPersistenceError from error
    return list(result.scalars().all())


class OrdersRepository:
    """Injectable façade over the Order-specific repository operations."""

    async def create_pending(
        self,
        session: AsyncSession,
        *,
        order_id: UUID,
        sku: str,
        quantity: int,
        request_id: str,
        trace_id: str | None,
    ) -> Order:
        return await create_pending_order(
            session,
            order_id=order_id,
            sku=sku,
            quantity=quantity,
            request_id=request_id,
            trace_id=trace_id,
        )

    async def change_status(
        self,
        session: AsyncSession,
        *,
        order_id: UUID,
        status: str,
        remaining_inventory: int | None,
        failure_reason: str | None,
    ) -> Order:
        return await change_order_status(
            session,
            order_id=order_id,
            status=status,
            remaining_inventory=remaining_inventory,
            failure_reason=failure_reason,
        )

    async def get_by_id(
        self,
        session: AsyncSession,
        order_id: UUID,
    ) -> Order | None:
        return await get_order_by_id(session, order_id)

    async def list_all(self, session: AsyncSession) -> list[Order]:
        return await list_orders(session)


repository = OrdersRepository()
