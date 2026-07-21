"""Centralized HTTP request metrics middleware."""

import time

from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from inventory_service.metrics import InventoryMetrics

METRICS_PATH = "/metrics"
UNMATCHED_ROUTE = "unmatched"


class MetricsMiddleware:
    """Record bounded HTTP metrics after a response is completed."""

    def __init__(self, app: ASGIApp, metrics: InventoryMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or scope.get("path") == METRICS_PATH:
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        status_code: int | None = None

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, capture_status)

        if status_code is None:
            return

        duration = max(0.0, time.perf_counter() - started_at)
        method = scope["method"]
        route = _route_template(scope)
        status = str(status_code)
        self.metrics.http_requests.labels(method, route, status).inc()
        self.metrics.http_request_duration.labels(method, route).observe(duration)
        if status_code >= 400:
            self.metrics.http_errors.labels(method, route, status).inc()


def _route_template(scope: Scope) -> str:
    """Return the matched route template without request-specific values."""
    route = scope.get("route")
    if isinstance(route, BaseRoute):
        path = getattr(route, "path", None)
        if isinstance(path, str):
            return path
    return UNMATCHED_ROUTE
