"""HTTP replay and conflict handling for idempotent Order creation."""

import logging

from fastapi import HTTPException, Response, status
from opentelemetry.trace import Span

from order_service.logging_config import LOGGER_NAME, SERVICE_NAME
from order_service.metrics import OrderMetrics
from order_service.models import Order
from order_service.schemas import OrderResponse

INVENTORY_UNAVAILABLE_DETAIL = "Inventory service unavailable."
logger = logging.getLogger(f"{LOGGER_NAME}.creation")


def normalize_idempotency_key(value: str | None) -> str | None:
    """Trim and validate the optional public key value."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must not be blank.",
        )
    if len(normalized) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must not exceed 255 characters.",
        )
    return normalized


def _set_replayed_trace_attributes(server_span: Span, order: Order) -> None:
    server_span.set_attributes(
        {
            "rootlens.order.id": str(order.id),
            "rootlens.order.persisted": True,
            "rootlens.order.status": order.status,
            "rootlens.order.outcome": order.failure_reason or order.status,
            "rootlens.order.idempotency_outcome": "replayed",
        }
    )


def _replay_completed_order(
    *,
    response: Response,
    order: Order,
    metrics: OrderMetrics,
    server_span: Span,
    request_id: str,
    key_hash: str,
) -> OrderResponse:
    replay_status = {
        ("confirmed", None): status.HTTP_201_CREATED,
        ("rejected", "item_not_found"): status.HTTP_404_NOT_FOUND,
        ("rejected", "insufficient_inventory"): status.HTTP_409_CONFLICT,
    }.get((order.status, order.failure_reason), status.HTTP_503_SERVICE_UNAVAILABLE)
    metrics.idempotency_events.labels("replayed").inc()
    _set_replayed_trace_attributes(server_span, order)
    logger.info(
        "order_idempotency_replayed",
        extra={
            "service": SERVICE_NAME,
            "order_id": str(order.id),
            "idempotency_key_hash": key_hash,
            "order_status": order.status,
            "replayed_http_status": replay_status,
            "request_id": request_id,
        },
    )
    replay_headers = {"Idempotency-Replayed": "true"}
    if order.status == "confirmed":
        response.headers.update(replay_headers)
        return OrderResponse(
            order_id=order.id,
            sku=order.sku,
            quantity=order.quantity,
            status="confirmed",
            remaining_inventory=order.remaining_inventory,
        )
    detail = {
        "item_not_found": "Inventory item not found.",
        "insufficient_inventory": "Insufficient inventory available.",
    }.get(order.failure_reason, INVENTORY_UNAVAILABLE_DETAIL)
    raise HTTPException(
        status_code=replay_status,
        detail=detail,
        headers=replay_headers,
    )


def handle_existing_claim(
    *,
    response: Response,
    order: Order,
    fingerprint: str,
    metrics: OrderMetrics,
    server_span: Span,
    request_id: str,
    key_hash: str,
) -> OrderResponse:
    """Return a stored result or raise the exact safe conflict response."""
    server_span.set_attribute("rootlens.order.id", str(order.id))
    if order.request_fingerprint != fingerprint:
        metrics.idempotency_events.labels("payload_mismatch").inc()
        server_span.set_attribute(
            "rootlens.order.idempotency_outcome", "payload_mismatch"
        )
        logger.warning(
            "order_idempotency_conflict",
            extra={
                "service": SERVICE_NAME,
                "idempotency_key_hash": key_hash,
                "reason": "payload_mismatch",
                "request_id": request_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used with a different request.",
        )
    if order.status == "pending":
        metrics.idempotency_events.labels("in_progress").inc()
        server_span.set_attributes(
            {
                "rootlens.order.persisted": True,
                "rootlens.order.status": "pending",
                "rootlens.order.idempotency_outcome": "in_progress",
            }
        )
        logger.warning(
            "order_idempotency_conflict",
            extra={
                "service": SERVICE_NAME,
                "order_id": str(order.id),
                "idempotency_key_hash": key_hash,
                "reason": "in_progress",
                "request_id": request_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An order with this idempotency key is still being processed.",
            headers={"Retry-After": "1"},
        )
    return _replay_completed_order(
        response=response,
        order=order,
        metrics=metrics,
        server_span=server_span,
        request_id=request_id,
        key_hash=key_hash,
    )
