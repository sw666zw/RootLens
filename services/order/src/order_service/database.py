"""Asynchronous PostgreSQL resources for the Order Service."""

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from order_service.logging_config import LOGGER_NAME


@dataclass(frozen=True)
class DatabaseResources:
    """Database resources owned by one Order Service application."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Release connections held by the engine pool."""
        await self.engine.dispose()


def create_database_resources(database_url: str | None = None) -> DatabaseResources:
    """Create testable async resources without opening a connection."""
    resolved_url = (
        database_url if database_url is not None else os.environ["ORDER_DATABASE_URL"]
    )
    engine = create_async_engine(resolved_url)
    return DatabaseResources(
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
    )


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session and close it afterward."""
    resources: DatabaseResources = request.app.state.database_resources
    async with resources.session_factory() as session:
        yield session


async def check_database_readiness(request: Request) -> bool:
    """Return whether Order PostgreSQL accepts a simple query."""
    resources: DatabaseResources = request.app.state.database_resources
    try:
        async with resources.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        request.app.state.metrics.database_ready.set(0)
        logging.getLogger(f"{LOGGER_NAME}.database").warning(
            "database_readiness_failed"
        )
        return False
    request.app.state.metrics.database_ready.set(1)
    return True
