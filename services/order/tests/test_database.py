"""Order database resource tests without a real database."""

import asyncio
import io
from typing import Any, cast

from fastapi import Request
from fastapi.testclient import TestClient as FastAPITestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from order_service.database import (
    DatabaseResources,
    check_database_readiness,
    get_database_session,
)
from order_service.logging_config import configure_logging
from order_service.main import create_app


class FakeSessionContext:
    def __init__(self) -> None:
        self.session = object()
        self.closed = False

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


class FakeSessionFactory:
    def __init__(self, context: FakeSessionContext) -> None:
        self.context = context

    def __call__(self) -> FakeSessionContext:
        return self.context


class FakeConnection:
    def __init__(self) -> None:
        self.statement: str | None = None

    async def __aenter__(self) -> "FakeConnection":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        self.statement = str(statement)


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.disposed = False

    def connect(self) -> FakeConnection:
        return self.connection

    async def dispose(self) -> None:
        self.disposed = True


class FailingEngine(FakeEngine):
    def connect(self) -> Any:
        class FailingConnection:
            async def __aenter__(self) -> None:
                raise RuntimeError("postgresql+asyncpg://user:secret@internal/orders")

            async def __aexit__(self, *args: object) -> None:
                return None

        return FailingConnection()


def resources(
    engine: FakeEngine,
    context: FakeSessionContext | None = None,
) -> DatabaseResources:
    session_context = context or FakeSessionContext()
    return DatabaseResources(
        engine=cast(AsyncEngine, engine),
        session_factory=cast(
            async_sessionmaker[AsyncSession],
            FakeSessionFactory(session_context),
        ),
    )


def test_session_dependency_closes_session() -> None:
    context = FakeSessionContext()
    application = create_app(resources=resources(FakeEngine(), context))
    request = Request({"type": "http", "app": application})

    async def use_session() -> object:
        dependency = get_database_session(request)
        session = await anext(dependency)
        await dependency.aclose()
        return session

    assert asyncio.run(use_session()) is context.session
    assert context.closed is True


def test_readiness_executes_select_one_and_hides_failure() -> None:
    engine = FakeEngine()
    application = create_app(resources=resources(engine))
    request = Request({"type": "http", "app": application})
    assert asyncio.run(check_database_readiness(request)) is True
    assert engine.connection.statement == "SELECT 1"

    output = io.StringIO()
    configure_logging(output)
    failing = create_app(resources=resources(FailingEngine()))
    failing_request = Request({"type": "http", "app": failing})
    assert asyncio.run(check_database_readiness(failing_request)) is False
    assert "database_readiness_failed" in output.getvalue()
    assert "secret" not in output.getvalue()


def test_shutdown_disposes_order_engine() -> None:
    engine = FakeEngine()
    application = create_app(resources=resources(engine))

    with FastAPITestClient(application):
        pass

    assert engine.disposed is True
