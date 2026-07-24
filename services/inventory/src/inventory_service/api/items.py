"""Create and read endpoints for inventory items."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_service.database import get_database_session
from inventory_service.logging_config import LOGGER_NAME, SERVICE_NAME
from inventory_service.metrics import InventoryMetrics
from inventory_service.repositories import inventory_items
from inventory_service.request_context import get_request_id
from inventory_service.schemas import (
    InventoryItemCreate,
    InventoryItemRead,
    InventoryReservationRequest,
    InventoryReservationResponse,
)
from inventory_service.tracing import set_current_span_attributes

router = APIRouter(prefix="/items", tags=["items"])
logger = logging.getLogger(f"{LOGGER_NAME}.reservation")


@router.post(
    "",
    response_model=InventoryItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    item_data: InventoryItemCreate,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> InventoryItemRead:
    """Create one inventory item."""
    try:
        item = await inventory_items.create_inventory_item(session, item_data)
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An inventory item with this SKU already exists.",
        ) from error
    return InventoryItemRead.model_validate(item)


@router.get("", response_model=list[InventoryItemRead])
async def list_items(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[InventoryItemRead]:
    """List all inventory items in ascending SKU order."""
    items = await inventory_items.list_inventory_items(session)
    return [
        InventoryItemRead.model_validate(item)
        for item in sorted(items, key=lambda item: item.sku)
    ]


@router.get("/{sku}", response_model=InventoryItemRead)
async def get_item(
    sku: str,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> InventoryItemRead:
    """Retrieve one inventory item by its exact SKU."""
    item = await inventory_items.get_inventory_item_by_sku(session, sku)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory item not found.",
        )
    return InventoryItemRead.model_validate(item)


@router.post(
    "/{sku}/reserve",
    response_model=InventoryReservationResponse,
    status_code=status.HTTP_200_OK,
)
async def reserve_item(
    request: Request,
    sku: str,
    reservation: InventoryReservationRequest,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> InventoryReservationResponse:
    """Atomically subtract a positive quantity from one inventory item."""
    metrics: InventoryMetrics = request.app.state.metrics
    log_fields = {
        "service": SERVICE_NAME,
        "request_id": get_request_id(),
        "sku": sku,
        "requested_quantity": reservation.quantity,
    }
    trace_fields: dict[str, object] = {
        "rootlens.inventory.operation": "reserve",
        "rootlens.inventory.sku": sku,
        "rootlens.inventory.requested_quantity": reservation.quantity,
    }
    set_current_span_attributes(trace_fields)
    try:
        result = await inventory_items.reserve_inventory_item(
            session,
            sku,
            reservation.quantity,
        )
    except inventory_items.InventoryItemNotFoundError as error:
        set_current_span_attributes({"rootlens.inventory.outcome": "item_not_found"})
        metrics.reservations.labels("rejected", "item_not_found").inc()
        logger.warning(
            "inventory_reservation_rejected",
            extra={**log_fields, "reason": "item_not_found"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory item not found.",
        ) from error
    except inventory_items.InsufficientInventoryError as error:
        set_current_span_attributes(
            {"rootlens.inventory.outcome": "insufficient_inventory"}
        )
        metrics.reservations.labels("rejected", "insufficient_inventory").inc()
        logger.warning(
            "inventory_reservation_rejected",
            extra={**log_fields, "reason": "insufficient_inventory"},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insufficient inventory available.",
        ) from error
    except inventory_items.InventoryReservationDatabaseError as error:
        set_current_span_attributes({"rootlens.inventory.outcome": "database_error"})
        span = trace.get_current_span()
        if span.is_recording():
            safe_error = inventory_items.InventoryReservationDatabaseError(
                "Inventory reservation database error"
            )
            span.record_exception(safe_error)
            span.set_status(Status(StatusCode.ERROR))
        metrics.reservations.labels("error", "database_error").inc()
        logger.error("inventory_reservation_failed", extra=log_fields)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to reserve inventory.",
        ) from error

    set_current_span_attributes({"rootlens.inventory.outcome": "success"})
    metrics.reservations.labels("success", "none").inc()
    logger.info(
        "inventory_reservation_succeeded",
        extra={**log_fields, "remaining_quantity": result.remaining_quantity},
    )
    return InventoryReservationResponse(
        sku=result.sku,
        reserved_quantity=result.reserved_quantity,
        remaining_quantity=result.remaining_quantity,
    )
