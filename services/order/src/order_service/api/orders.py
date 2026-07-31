"""Persistent order lifecycle and read endpoints."""

import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, Tracer
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.clients import (
    InsufficientInventoryError,
    InventoryClient,
    InventoryInvalidResponseError,
    InventoryItemNotFoundError,
    InventoryMalformedResponseError,
    InventoryUnavailableError,
)
from order_service.database import get_database_session
from order_service.logging_config import LOGGER_NAME, SERVICE_NAME
from order_service.metrics import OrderMetrics
from order_service.repositories import orders
from order_service.request_context import get_request_id
from order_service.schemas import (
    OrderCreate,
    OrderResponse,
    PersistedOrderResponse,
)
from order_service.tracing import current_trace_ids

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger(f"{LOGGER_NAME}.creation")
ORDER_UNAVAILABLE_DETAIL = "Order service unavailable."


@dataclass(frozen=True)
class FailedOutcome:
    """Safe downstream failure details used for persistence and HTTP mapping."""

    status: str
    failure_reason: str
    http_status: int
    detail: str
    creation_message: str
    creation_level: int
    metric_outcome: str


def get_inventory_client(request: Request) -> InventoryClient:
    """Return the application-owned Inventory client."""
    return request.app.state.inventory_client


def get_order_repository() -> orders.OrdersRepository:
    """Return the stateless Order repository façade."""
    return orders.repository


def _record_safe_database_error(span: Span) -> None:
    safe_error = orders.OrderPersistenceError("Order persistence error")
    span.record_exception(safe_error)
    span.set_status(Status(StatusCode.ERROR))


def _log_persistence_failure(
    *,
    order_id: UUID,
    operation: str,
    persisted_status: str,
    request_id: str,
) -> None:
    logger.error(
        "order_persistence_failed",
        extra={
            "service": SERVICE_NAME,
            "order_id": str(order_id),
            "operation": operation,
            "status": persisted_status,
            "request_id": request_id,
            "reason": "database_error",
        },
    )


async def _persist_result(
    session: AsyncSession,
    repository: orders.OrdersRepository,
    metrics: OrderMetrics,
    server_span: Span,
    persistence_tracer: Tracer,
    *,
    order_id: UUID,
    new_status: str,
    remaining_inventory: int | None,
    failure_reason: str | None,
    request_id: str,
) -> None:
    try:
        with persistence_tracer.start_as_current_span(
            "order.persist_result",
            record_exception=False,
            set_status_on_exception=False,
        ):
            await repository.change_status(
                session,
                order_id=order_id,
                status=new_status,
                remaining_inventory=remaining_inventory,
                failure_reason=failure_reason,
            )
    except (orders.OrderPersistenceError, orders.PersistedOrderNotFoundError) as error:
        _log_persistence_failure(
            order_id=order_id,
            operation="persist_result",
            persisted_status=new_status,
            request_id=request_id,
        )
        server_span.set_attribute("rootlens.order.persisted", False)
        server_span.set_attribute(
            "rootlens.order.failure_reason", "order_persistence_failure"
        )
        _record_safe_database_error(server_span)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ORDER_UNAVAILABLE_DETAIL,
        ) from error

    metrics.status_transitions.labels("pending", new_status).inc()
    server_span.set_attribute("rootlens.order.persisted", True)
    server_span.set_attribute("rootlens.order.status", new_status)
    if failure_reason is not None:
        server_span.set_attribute("rootlens.order.failure_reason", failure_reason)
    log_method = {
        "confirmed": logger.info,
        "rejected": logger.warning,
        "failed": logger.error,
    }[new_status]
    transition_fields: dict[str, object] = {
        "service": SERVICE_NAME,
        "order_id": str(order_id),
        "previous_status": "pending",
        "new_status": new_status,
        "request_id": request_id,
    }
    if failure_reason is not None:
        transition_fields["failure_reason"] = failure_reason
    if remaining_inventory is not None:
        transition_fields["remaining_inventory"] = remaining_inventory
    log_method("order_status_changed", extra=transition_fields)


def _failed_outcome(error: Exception) -> FailedOutcome:
    if isinstance(error, InventoryItemNotFoundError):
        return FailedOutcome(
            "rejected",
            "item_not_found",
            status.HTTP_404_NOT_FOUND,
            "Inventory item not found.",
            "order_creation_rejected",
            logging.WARNING,
            "rejected",
        )
    if isinstance(error, InsufficientInventoryError):
        return FailedOutcome(
            "rejected",
            "insufficient_inventory",
            status.HTTP_409_CONFLICT,
            "Insufficient inventory available.",
            "order_creation_rejected",
            logging.WARNING,
            "rejected",
        )
    if isinstance(
        error,
        (InventoryInvalidResponseError, InventoryMalformedResponseError),
    ):
        reason = "inventory_invalid_response"
    else:
        reason = "inventory_unavailable"
    return FailedOutcome(
        "failed",
        reason,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Inventory service unavailable.",
        "order_creation_failed",
        logging.ERROR,
        "error",
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    request: Request,
    order_data: OrderCreate,
    inventory: Annotated[InventoryClient, Depends(get_inventory_client)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
    repository: Annotated[
        orders.OrdersRepository,
        Depends(get_order_repository),
    ],
) -> OrderResponse:
    """Persist a complete order attempt around one Inventory reservation."""
    metrics: OrderMetrics = request.app.state.metrics
    request_id = get_request_id()
    if request_id is None:
        raise RuntimeError("Request ID middleware is not configured.")

    order_id = uuid4()
    trace_ids = current_trace_ids()
    trace_id = trace_ids[0] if trace_ids is not None else None
    server_span = trace.get_current_span()
    tracing_resources = request.app.state.tracing
    persistence_tracer = (
        tracing_resources.provider.get_tracer(__name__)
        if tracing_resources is not None
        else trace.get_tracer(__name__)
    )
    server_span.set_attributes(
        {
            "rootlens.order.operation": "create",
            "rootlens.order.id": str(order_id),
            "rootlens.order.sku": order_data.sku,
            "rootlens.order.quantity": order_data.quantity,
            "rootlens.order.persisted": False,
            "rootlens.order.status": "pending",
        }
    )
    log_fields = {
        "service": SERVICE_NAME,
        "request_id": request_id,
        "order_id": str(order_id),
        "sku": order_data.sku,
        "quantity": order_data.quantity,
    }

    try:
        with persistence_tracer.start_as_current_span(
            "order.persist_pending",
            record_exception=False,
            set_status_on_exception=False,
        ):
            await repository.create_pending(
                session,
                order_id=order_id,
                sku=order_data.sku,
                quantity=order_data.quantity,
                request_id=request_id,
                trace_id=trace_id,
            )
    except orders.OrderPersistenceError as error:
        _log_persistence_failure(
            order_id=order_id,
            operation="persist_pending",
            persisted_status="pending",
            request_id=request_id,
        )
        server_span.set_attribute(
            "rootlens.order.failure_reason", "order_persistence_failure"
        )
        _record_safe_database_error(server_span)
        metrics.creations.labels("error", "order_persistence_failure").inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ORDER_UNAVAILABLE_DETAIL,
        ) from error

    metrics.status_transitions.labels("none", "pending").inc()
    server_span.set_attribute("rootlens.order.persisted", True)
    logger.info(
        "order_persistence_started",
        extra={**log_fields, "status": "pending"},
    )

    try:
        reservation = await inventory.reserve(
            order_data.sku,
            order_data.quantity,
            request_id,
        )
    except (
        InventoryItemNotFoundError,
        InsufficientInventoryError,
        InventoryInvalidResponseError,
        InventoryMalformedResponseError,
        InventoryUnavailableError,
    ) as error:
        outcome = _failed_outcome(error)
        await _persist_result(
            session,
            repository,
            metrics,
            server_span,
            persistence_tracer,
            order_id=order_id,
            new_status=outcome.status,
            remaining_inventory=None,
            failure_reason=outcome.failure_reason,
            request_id=request_id,
        )
        server_span.set_attribute("rootlens.order.outcome", outcome.failure_reason)
        metrics.creations.labels(outcome.metric_outcome, outcome.failure_reason).inc()
        logger.log(
            outcome.creation_level,
            outcome.creation_message,
            extra={**log_fields, "reason": outcome.failure_reason},
        )
        raise HTTPException(
            status_code=outcome.http_status,
            detail=outcome.detail,
        ) from error

    try:
        await _persist_result(
            session,
            repository,
            metrics,
            server_span,
            persistence_tracer,
            order_id=order_id,
            new_status="confirmed",
            remaining_inventory=reservation.remaining_quantity,
            failure_reason=None,
            request_id=request_id,
        )
    except HTTPException:
        logger.error(
            "order_consistency_risk",
            extra={
                **log_fields,
                "status": "pending",
                "reason": "inventory_reserved_final_status_not_persisted",
            },
        )
        raise

    server_span.set_attribute("rootlens.order.outcome", "confirmed")
    metrics.creations.labels("confirmed", "none").inc()
    logger.info(
        "order_creation_succeeded",
        extra={
            **log_fields,
            "remaining_inventory": reservation.remaining_quantity,
        },
    )
    return OrderResponse(
        order_id=order_id,
        sku=order_data.sku,
        quantity=order_data.quantity,
        status="confirmed",
        remaining_inventory=reservation.remaining_quantity,
    )


@router.get("", response_model=list[PersistedOrderResponse])
async def get_orders(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    repository: Annotated[
        orders.OrdersRepository,
        Depends(get_order_repository),
    ],
) -> list[PersistedOrderResponse]:
    """Return every persisted order in deterministic order."""
    try:
        persisted = await repository.list_all(session)
    except orders.OrderPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ORDER_UNAVAILABLE_DETAIL,
        ) from error
    return [PersistedOrderResponse.model_validate(order) for order in persisted]


@router.get("/{order_id}", response_model=PersistedOrderResponse)
async def get_order(
    order_id: UUID,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    repository: Annotated[
        orders.OrdersRepository,
        Depends(get_order_repository),
    ],
) -> PersistedOrderResponse:
    """Return one persisted order or the stable not-found response."""
    try:
        persisted = await repository.get_by_id(session, order_id)
    except orders.OrderPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ORDER_UNAVAILABLE_DETAIL,
        ) from error
    if persisted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )
    return PersistedOrderResponse.model_validate(persisted)
