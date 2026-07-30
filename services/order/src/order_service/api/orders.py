"""Transient order creation endpoint."""

import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from order_service.clients import (
    InsufficientInventoryError,
    InventoryClient,
    InventoryInvalidResponseError,
    InventoryItemNotFoundError,
    InventoryMalformedResponseError,
    InventoryUnavailableError,
)
from order_service.logging_config import LOGGER_NAME, SERVICE_NAME
from order_service.metrics import OrderMetrics
from order_service.request_context import get_request_id
from order_service.schemas import OrderCreate, OrderResponse
from order_service.tracing import set_current_span_attributes

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger(f"{LOGGER_NAME}.creation")


def get_inventory_client(request: Request) -> InventoryClient:
    """Return the application-owned Inventory client."""
    return request.app.state.inventory_client


def _record_outcome(
    metrics: OrderMetrics,
    span_outcome: str,
    metric_outcome: str,
    metric_reason: str,
) -> None:
    set_current_span_attributes({"rootlens.order.outcome": span_outcome})
    metrics.creations.labels(metric_outcome, metric_reason).inc()


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    request: Request,
    order: OrderCreate,
    inventory: Annotated[InventoryClient, Depends(get_inventory_client)],
) -> OrderResponse:
    """Reserve inventory and confirm a non-persistent order."""
    metrics: OrderMetrics = request.app.state.metrics
    request_id = get_request_id()
    if request_id is None:
        raise RuntimeError("Request ID middleware is not configured.")

    log_fields = {
        "service": SERVICE_NAME,
        "request_id": request_id,
        "sku": order.sku,
        "quantity": order.quantity,
    }
    set_current_span_attributes(
        {
            "rootlens.order.operation": "create",
            "rootlens.order.sku": order.sku,
            "rootlens.order.quantity": order.quantity,
        }
    )

    try:
        reservation = await inventory.reserve(
            order.sku,
            order.quantity,
            request_id,
        )
    except InventoryItemNotFoundError as error:
        reason = "item_not_found"
        _record_outcome(metrics, reason, "rejected", reason)
        logger.warning(
            "order_creation_rejected",
            extra={**log_fields, "reason": reason},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory item not found.",
        ) from error
    except InsufficientInventoryError as error:
        reason = "insufficient_inventory"
        _record_outcome(metrics, reason, "rejected", reason)
        logger.warning(
            "order_creation_rejected",
            extra={**log_fields, "reason": reason},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insufficient inventory available.",
        ) from error
    except InventoryInvalidResponseError as error:
        reason = "inventory_invalid_response"
        _record_outcome(metrics, reason, "error", reason)
        logger.error(
            "order_creation_failed",
            extra={**log_fields, "reason": reason},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Inventory service returned an invalid response.",
        ) from error
    except InventoryMalformedResponseError as error:
        reason = "inventory_invalid_response"
        _record_outcome(metrics, reason, "error", reason)
        logger.error(
            "order_creation_failed",
            extra={**log_fields, "reason": reason},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory service unavailable.",
        ) from error
    except InventoryUnavailableError as error:
        reason = "inventory_unavailable"
        _record_outcome(metrics, reason, "error", reason)
        logger.error(
            "order_creation_failed",
            extra={**log_fields, "reason": reason},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory service unavailable.",
        ) from error

    order_id = uuid4()
    _record_outcome(metrics, "confirmed", "confirmed", "none")
    logger.info(
        "order_creation_succeeded",
        extra={
            **log_fields,
            "order_id": str(order_id),
            "remaining_inventory": reservation.remaining_quantity,
        },
    )
    return OrderResponse(
        order_id=order_id,
        sku=order.sku,
        quantity=order.quantity,
        status="confirmed",
        remaining_inventory=reservation.remaining_quantity,
    )
