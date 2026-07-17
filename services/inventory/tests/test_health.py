from uuid import UUID

from fastapi import Request
from fastapi.testclient import TestClient as FastAPITestClient

from inventory_service.database import check_database_readiness
from inventory_service.main import create_app
from inventory_service.request_context import get_request_id


async def database_is_ready() -> bool:
    return True


async def database_is_unavailable() -> bool:
    return False


def test_health() -> None:
    client = FastAPITestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "inventory",
    }


def test_health_generates_request_id() -> None:
    client = FastAPITestClient(create_app())

    response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id


def test_health_preserves_supplied_request_id() -> None:
    client = FastAPITestClient(create_app())

    response = client.get("/health", headers={"X-Request-ID": "caller-id-123"})

    assert response.headers["X-Request-ID"] == "caller-id-123"


def test_blank_request_id_is_replaced_with_uuid() -> None:
    client = FastAPITestClient(create_app())

    response = client.get("/health", headers={"X-Request-ID": ""})

    assert (
        str(UUID(response.headers["X-Request-ID"])) == response.headers["X-Request-ID"]
    )


def test_request_id_is_available_in_request_context() -> None:
    application = create_app()

    @application.get("/request-context")
    def request_context(request: Request) -> dict[str, str | None]:
        return {
            "state": request.state.request_id,
            "context": get_request_id(),
        }

    client = FastAPITestClient(application)

    response = client.get(
        "/request-context",
        headers={"X-Request-ID": "context-id"},
    )

    assert response.json() == {"state": "context-id", "context": "context-id"}


def test_readiness_when_database_is_reachable() -> None:
    application = create_app()
    application.dependency_overrides[check_database_readiness] = database_is_ready
    client = FastAPITestClient(application)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "inventory",
        "database": "ok",
    }


def test_readiness_when_database_is_unreachable() -> None:
    application = create_app()
    application.dependency_overrides[check_database_readiness] = database_is_unavailable
    client = FastAPITestClient(application)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "inventory",
        "database": "unavailable",
    }


def test_readiness_response_does_not_expose_database_secrets() -> None:
    application = create_app()
    application.dependency_overrides[check_database_readiness] = database_is_unavailable
    client = FastAPITestClient(application)

    response = client.get("/health/ready")

    assert "postgresql+asyncpg://" not in response.text
    assert "rootlens_dev_password" not in response.text


def test_readiness_preserves_supplied_request_id() -> None:
    application = create_app()
    application.dependency_overrides[check_database_readiness] = database_is_ready
    client = FastAPITestClient(application)

    response = client.get(
        "/health/ready",
        headers={"X-Request-ID": "readiness-id"},
    )

    assert response.headers["X-Request-ID"] == "readiness-id"
