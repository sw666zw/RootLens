"""Normalized-route HTTP metrics middleware."""

import time

from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from diagnosis_service.metrics import DiagnosisMetrics


class MetricsMiddleware:
    def __init__(self, app: ASGIApp, metrics: DiagnosisMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status: int | None = None

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive, capture)
        if status is None:
            return
        route = "unmatched"
        matched = scope.get("route")
        if isinstance(matched, BaseRoute) and isinstance(
            getattr(matched, "path", None), str
        ):
            route = matched.path
        method = scope["method"]
        self.metrics.http_requests.labels(method, route, str(status)).inc()
        self.metrics.http_duration.labels(method, route).observe(
            max(0.0, time.perf_counter() - started)
        )
        if status >= 400:
            self.metrics.http_errors.labels(method, route, str(status)).inc()
