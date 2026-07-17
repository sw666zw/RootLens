"""Request ID propagation and completion logging middleware."""

import logging
import time
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from inventory_service.logging_config import LOGGER_NAME, SERVICE_NAME
from inventory_service.request_context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware:
    """Attach a request ID and emit one structured log for each request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._logger = logging.getLogger(f"{LOGGER_NAME}.request")

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        supplied_request_id = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = (
            supplied_request_id if supplied_request_id.strip() else str(uuid4())
        )
        request.state.request_id = request_id
        context_token = set_request_id(request_id)
        started_at = time.perf_counter()

        request_fields: dict[str, object] = {
            "service": SERVICE_NAME,
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }
        status_code: int | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000)
            self._logger.exception(
                "request_failed",
                extra={**request_fields, "duration_ms": duration_ms},
            )
            raise
        else:
            duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000)
            self._logger.info(
                "request_completed",
                extra={
                    **request_fields,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
        finally:
            reset_request_id(context_token)
