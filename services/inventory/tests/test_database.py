import asyncio
import io
from typing import Any, cast

from fastapi import Request
from fastapi.testclient import TestClient as FastAPITestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from inventory_service.database import (
    DatabaseResources,
    check_database_readiness,
    get_database_session,
)
from inventory_service.logging_config import configure_logging
from inventory_service.main import create_app


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
    def __init__(self, connection: FakeConnection | None = None) -> None:
        self.connection = connection or FakeConnection()
        self.disposed = False

    def connect(self) -> FakeConnection:
        return self.connection

    async def dispose(self) -> None:
        self.disposed = True


class FailingConnection:
    async def __aenter__(self) -> None:
        raise RuntimeError(
            "postgresql+asyncpg://rootlens:secret@database.internal/inventory"
        )

    async def __aexit__(self, *args: object) -> None:
        return None


class FailingEngine(FakeEngine):
    def connect(self) -> Any:
        return FailingConnection()


def make_resources(
    engine: FakeEngine,
    session_factory: FakeSessionFactory | None = None,
) -> DatabaseResources:
    factory = session_factory or FakeSessionFactory(FakeSessionContext())
    return DatabaseResources(
        engine=cast(AsyncEngine, engine),
        session_factory=cast(async_sessionmaker[AsyncSession], factory),
    )


def test_database_session_dependency_cleans_up_session() -> None:
    context = FakeSessionContext()
    resources = make_resources(FakeEngine(), FakeSessionFactory(context))
    application = create_app(resources)
    request = Request({"type": "http", "app": application})

    async def use_dependency() -> object:
        dependency = get_database_session(request)
        session = await anext(dependency)
        await dependency.aclose()
        return session

    session = asyncio.run(use_dependency())

    assert session is context.session
    assert context.closed is True


def test_database_readiness_executes_select_one() -> None:
    engine = FakeEngine()
    application = create_app(make_resources(engine))
    request = Request({"type": "http", "app": application})

    result = asyncio.run(check_database_readiness(request))

    assert result is True
    assert engine.connection.statement == "SELECT 1"


def test_database_readiness_logs_failure_without_secret() -> None:
    output = io.StringIO()
    configure_logging(output)
    application = create_app(make_resources(FailingEngine()))
    request = Request({"type": "http", "app": application})

    result = asyncio.run(check_database_readiness(request))

    assert result is False
    assert "database_readiness_failed" in output.getvalue()
    assert "secret" not in output.getvalue()
    assert "postgresql+asyncpg://" not in output.getvalue()


def test_application_shutdown_disposes_database_engine() -> None:
    engine = FakeEngine()
    application = create_app(make_resources(engine))

    with FastAPITestClient(application):
        pass

    assert engine.disposed is True
