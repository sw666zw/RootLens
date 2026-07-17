"""Asynchronous PostgreSQL resources for the Inventory Service."""

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

from inventory_service.logging_config import LOGGER_NAME


@dataclass(frozen=True)
class DatabaseResources:
    """Database resources owned by one Inventory Service application."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Release connections held by the engine's pool."""
        await self.engine.dispose()


def create_database_resources(database_url: str | None = None) -> DatabaseResources:
    """Create testable async database resources without opening a connection."""
    resolved_url = (
        database_url if database_url is not None else os.environ["DATABASE_URL"]
    )
    engine = create_async_engine(resolved_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return DatabaseResources(engine=engine, session_factory=session_factory)


database_resources = create_database_resources()
engine = database_resources.engine
async_session_factory = database_resources.session_factory


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one database session and close it after the request finishes."""
    resources: DatabaseResources = request.app.state.database_resources
    async with resources.session_factory() as session:
        yield session


async def check_database_readiness(request: Request) -> bool:
    """Return whether PostgreSQL accepts a simple query."""
    resources: DatabaseResources = request.app.state.database_resources
    try:
        async with resources.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logging.getLogger(f"{LOGGER_NAME}.database").warning(
            "database_readiness_failed"
        )
        return False
    return True
