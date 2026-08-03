"""HTTP client for local Inventory controls and Order business traffic."""

import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from rootlens_scenarios.models import RequestObservation

TRACE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


def validate_service_url(value: str, name: str) -> str:
    """Validate an HTTP base URL without ever printing its value."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP or HTTPS URL")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not contain a query or fragment")
    return value.strip().rstrip("/")


def valid_trace_id(value: str | None) -> str | None:
    """Normalize a valid nonzero returned W3C trace ID."""
    if value is None or TRACE_ID_PATTERN.fullmatch(value) is None:
        return None
    normalized = value.lower()
    return normalized if normalized != "0" * 32 else None


class ScenarioClient:
    """Use one reusable client for each business service."""

    def __init__(
        self,
        inventory: httpx.AsyncClient,
        order: httpx.AsyncClient,
    ) -> None:
        self._inventory = inventory
        self._order = order

    @classmethod
    def create(
        cls,
        inventory_url: str,
        order_url: str,
    ) -> "ScenarioClient":
        timeout = httpx.Timeout(15.0, connect=5.0)
        return cls(
            httpx.AsyncClient(
                base_url=validate_service_url(inventory_url, "INVENTORY_SERVICE_URL"),
                timeout=timeout,
            ),
            httpx.AsyncClient(
                base_url=validate_service_url(order_url, "ORDER_SERVICE_URL"),
                timeout=timeout,
            ),
        )

    async def __aenter__(self) -> "ScenarioClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._inventory.aclose()
        await self._order.aclose()

    @staticmethod
    async def _request(
        client: httpx.AsyncClient,
        method: str,
        path: str,
        operation: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make one request while keeping credential-bearing URLs out of errors."""
        try:
            return await client.request(method, path, **kwargs)
        except httpx.RequestError as error:
            raise RuntimeError(f"{operation} failed") from error

    async def check_health(self) -> None:
        """Require both service liveness endpoints before scenario setup."""
        for name, client in (
            ("Inventory", self._inventory),
            ("Order", self._order),
        ):
            response = await self._request(
                client, "GET", "/health", f"{name} health check"
            )
            if response.status_code != 200:
                raise RuntimeError(f"{name} health check failed")

    async def create_inventory_item(self, sku: str, quantity: int) -> None:
        response = await self._request(
            self._inventory,
            "POST",
            "/items",
            "Inventory scenario item creation",
            json={"sku": sku, "name": f"Scenario {sku}", "quantity": quantity},
        )
        if response.status_code != 201:
            raise RuntimeError("Inventory scenario item creation failed")

    async def configure_fault(self, delay_ms: int, failure_mode: str) -> None:
        response = await self._request(
            self._inventory,
            "PUT",
            "/internal/faults/reservation",
            "Inventory fault configuration",
            json={"delay_ms": delay_ms, "failure_mode": failure_mode},
        )
        if response.status_code != 200:
            raise RuntimeError("Inventory fault configuration failed")

    async def reset_fault(self) -> None:
        response = await self._request(
            self._inventory,
            "DELETE",
            "/internal/faults/reservation",
            "Inventory fault reset",
        )
        if response.status_code != 200:
            raise RuntimeError("Inventory fault reset failed")

    async def inventory_quantity(self, sku: str) -> int | None:
        try:
            response = await self._request(
                self._inventory,
                "GET",
                f"/items/{sku}",
                "Inventory quantity verification",
            )
        except RuntimeError:
            return None
        if response.status_code != 200:
            return None
        quantity = response.json().get("quantity")
        if isinstance(quantity, int) and not isinstance(quantity, bool):
            return quantity
        return None

    async def create_order(
        self,
        sku: str,
        request_id: str,
        idempotency_key: str,
    ) -> RequestObservation:
        started = time.perf_counter()
        status_code: int | None = None
        returned_request_id = request_id
        trace_id: str | None = None
        try:
            response = await self._order.post(
                "/orders",
                json={"sku": sku, "quantity": 1},
                headers={
                    "X-Request-ID": request_id,
                    "Idempotency-Key": idempotency_key,
                },
            )
            status_code = response.status_code
            returned_request_id = response.headers.get("X-Request-ID", request_id)
            trace_id = valid_trace_id(response.headers.get("X-Trace-ID"))
        except httpx.RequestError:
            pass
        duration_ms = max(0.0, (time.perf_counter() - started) * 1000)
        return RequestObservation(
            status_code=status_code,
            duration_ms=duration_ms,
            request_id=returned_request_id,
            trace_id=trace_id,
        )
