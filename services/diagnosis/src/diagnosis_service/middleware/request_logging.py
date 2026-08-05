"""Request ID propagation and safe completion logging."""

import logging
import time
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from diagnosis_service.logging_config import LOGGER_NAME
from diagnosis_service.request_context import reset_request_id, set_request_id
from diagnosis_service.tracing import current_trace_ids, set_span_attributes


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger(f"{LOGGER_NAME}.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if supplied.strip() else str(uuid4())
        request.state.request_id = request_id
        token = set_request_id(request_id)
        set_span_attributes({"rootlens.request_id": request_id})
        started = time.perf_counter()
        status: int | None = None

        async def correlate(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                trace_ids = current_trace_ids()
                if trace_ids:
                    headers["X-Trace-ID"] = trace_ids[0]
            await send(message)

        try:
            await self.app(scope, receive, correlate)
        finally:
            self.logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status,
                    "duration_ms": max(0.0, (time.perf_counter() - started) * 1000),
                },
            )
            reset_request_id(token)
