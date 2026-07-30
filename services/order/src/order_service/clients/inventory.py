"""Safe translation layer for Inventory Service reservations."""

from dataclasses import dataclass
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, ValidationError


class InventoryClientError(Exception):
    """Base class for safe downstream errors."""


class InventoryItemNotFoundError(InventoryClientError):
    """Raised when Inventory returns 404."""


class InsufficientInventoryError(InventoryClientError):
    """Raised when Inventory returns 409."""


class InventoryInvalidResponseError(InventoryClientError):
    """Raised when Inventory explicitly rejects the request as invalid."""


class InventoryMalformedResponseError(InventoryClientError):
    """Raised when Inventory returns data that cannot be trusted."""


class InventoryUnavailableError(InventoryClientError):
    """Raised when Inventory cannot safely complete the request."""


class _ReservationResponse(BaseModel):
    sku: str = Field(min_length=1, max_length=64, strict=True)
    reserved_quantity: int = Field(gt=0, strict=True)
    remaining_quantity: int = Field(ge=0, strict=True)


@dataclass(frozen=True)
class ReservationResult:
    """Validated reservation values."""

    remaining_quantity: int


class InventoryClient:
    """Reserve Inventory stock through one reusable HTTPX client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def reserve(
        self,
        sku: str,
        quantity: int,
        request_id: str,
    ) -> ReservationResult:
        """Reserve stock and expose only safe, typed outcomes."""
        encoded_sku = quote(sku, safe="")
        try:
            response = await self._client.post(
                f"/items/{encoded_sku}/reserve",
                json={"quantity": quantity},
                headers={"X-Request-ID": request_id},
            )
        except (httpx.TimeoutException, httpx.RequestError) as error:
            raise InventoryUnavailableError from error

        if response.status_code == 404:
            raise InventoryItemNotFoundError
        if response.status_code == 409:
            raise InsufficientInventoryError
        if response.status_code == 422:
            raise InventoryInvalidResponseError
        if response.status_code >= 500:
            raise InventoryUnavailableError
        if response.status_code != 200:
            raise InventoryInvalidResponseError

        try:
            payload = _ReservationResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise InventoryMalformedResponseError from error
        if payload.sku != sku or payload.reserved_quantity != quantity:
            raise InventoryMalformedResponseError
        return ReservationResult(remaining_quantity=payload.remaining_quantity)
