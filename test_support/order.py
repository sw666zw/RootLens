"""Order Service test doubles and Prometheus helpers."""

import json
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import httpx
from fastapi.testclient import TestClient as FastAPITestClient
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.api.orders import get_order_repository
from order_service.config import Settings
from order_service.database import get_database_session
from order_service.main import create_app
from order_service.repositories.orders import OrdersRepository
from order_service.repositories.orders import PendingOrderClaim
from order_service.tracing import TracingConfiguration

Handler = Callable[[httpx.Request], httpx.Response]


class InMemoryOrdersRepository(OrdersRepository):
    """Order repository test double with a durable in-memory lifecycle."""

    def __init__(self) -> None:
        self.orders: dict[UUID, SimpleNamespace] = {}
        self.events: list[tuple[str, str]] = []
        self._claim_lock = threading.Lock()

    async def create_pending(
        self,
        session: AsyncSession,
        *,
        order_id: UUID,
        sku: str,
        quantity: int,
        request_id: str,
        trace_id: str | None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> SimpleNamespace:
        del session
        now = datetime.now(UTC)
        order = SimpleNamespace(
            id=order_id,
            sku=sku,
            quantity=quantity,
            status="pending",
            remaining_inventory=None,
            failure_reason=None,
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            created_at=now,
            updated_at=now,
        )
        self.orders[order_id] = order
        self.events.append(("persist", "pending"))
        return order

    async def claim_pending(
        self,
        session: AsyncSession,
        *,
        order_id: UUID,
        sku: str,
        quantity: int,
        request_id: str,
        trace_id: str | None,
        idempotency_key: str | None,
        request_fingerprint: str | None,
    ) -> PendingOrderClaim:
        if idempotency_key is not None:
            with self._claim_lock:
                existing = next(
                    (
                        order
                        for order in self.orders.values()
                        if order.idempotency_key == idempotency_key
                    ),
                    None,
                )
                if existing is not None:
                    return PendingOrderClaim(order=existing, claimed=False)
                order = await self.create_pending(
                    session,
                    order_id=order_id,
                    sku=sku,
                    quantity=quantity,
                    request_id=request_id,
                    trace_id=trace_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                return PendingOrderClaim(order=order, claimed=True)
        order = await self.create_pending(
            session,
            order_id=order_id,
            sku=sku,
            quantity=quantity,
            request_id=request_id,
            trace_id=trace_id,
        )
        return PendingOrderClaim(order=order, claimed=True)

    async def change_status(
        self,
        session: AsyncSession,
        *,
        order_id: UUID,
        status: str,
        remaining_inventory: int | None,
        failure_reason: str | None,
    ) -> SimpleNamespace:
        del session
        order = self.orders[order_id]
        order.status = status
        order.remaining_inventory = remaining_inventory
        order.failure_reason = failure_reason
        order.updated_at = datetime.now(UTC)
        self.events.append(("persist", status))
        return order

    async def get_by_id(
        self,
        session: AsyncSession,
        order_id: UUID,
    ) -> SimpleNamespace | None:
        del session
        return self.orders.get(order_id)

    async def get_by_idempotency_key(
        self,
        session: AsyncSession,
        idempotency_key: str,
    ) -> SimpleNamespace | None:
        del session
        return next(
            (
                order
                for order in self.orders.values()
                if order.idempotency_key == idempotency_key
            ),
            None,
        )

    async def list_all(self, session: AsyncSession) -> list[SimpleNamespace]:
        del session
        return sorted(
            self.orders.values(),
            key=lambda order: (-order.created_at.timestamp(), order.id),
        )


def make_client(
    handler: Handler,
    tracing: TracingConfiguration | None = None,
    repository: OrdersRepository | None = None,
) -> FastAPITestClient:
    """Create an app whose only downstream transport is in memory."""

    def client_factory(_: Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://inventory.test",
            timeout=5.0,
            transport=httpx.MockTransport(handler),
        )

    application = create_app(tracing=tracing, http_client_factory=client_factory)
    resolved_repository = repository or InMemoryOrdersRepository()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_order_repository] = lambda: resolved_repository
    application.state.test_repository = resolved_repository
    return FastAPITestClient(application)


def successful_inventory(request: httpx.Request) -> httpx.Response:
    """Return a valid reservation response matching the request."""
    quantity = json.loads(request.content)["quantity"]
    sku = request.url.path.split("/")[2]
    return httpx.Response(
        200,
        json={
            "sku": sku,
            "reserved_quantity": quantity,
            "remaining_quantity": 8,
        },
    )


def scrape(client: FastAPITestClient) -> str:
    """Return one successful Prometheus scrape."""
    response = client.get("/metrics")
    assert response.status_code == 200
    return response.text


def sample_values(
    exposition: str,
    name: str,
    labels: dict[str, str],
) -> list[float]:
    """Return sample values exactly matching one name and label set."""
    return [
        sample.value
        for family in text_string_to_metric_families(exposition)
        for sample in family.samples
        if sample.name == name and sample.labels == labels
    ]
