"""Prometheus exposition endpoint."""

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from order_service.metrics import OrderMetrics

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """Expose metrics from this application's isolated registry."""
    application_metrics: OrderMetrics = request.app.state.metrics
    return Response(
        content=generate_latest(application_metrics.registry),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )
