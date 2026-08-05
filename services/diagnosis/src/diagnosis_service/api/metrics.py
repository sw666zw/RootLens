"""Prometheus exposition endpoint."""

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    return Response(
        generate_latest(request.app.state.metrics.registry),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )
