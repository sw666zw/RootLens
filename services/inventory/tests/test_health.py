from uuid import UUID

from fastapi import Request
from fastapi.testclient import TestClient as FastAPITestClient

from inventory_service.main import create_app
from inventory_service.request_context import get_request_id


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

    assert str(UUID(response.headers["X-Request-ID"])) == response.headers[
        "X-Request-ID"
    ]


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
