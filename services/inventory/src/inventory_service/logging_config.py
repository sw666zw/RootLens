"""Structured logging configuration for the Inventory Service."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TextIO

SERVICE_NAME = "inventory"
LOGGER_NAME = "inventory_service"
_HANDLER_MARKER = "_inventory_json_handler"
_REQUEST_FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
)


class JsonFormatter(logging.Formatter):
    """Format Inventory Service application logs as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, "service", SERVICE_NAME),
        }

        for field in _REQUEST_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


def configure_logging(stream: TextIO | None = None) -> logging.Logger:
    """Configure the application logger without accumulating handlers."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, _HANDLER_MARKER, False)
    ]
    destination = stream if stream is not None else sys.stderr

    if handlers and (stream is None or handlers[0].stream is destination):
        handler = handlers[0]
        for duplicate in handlers[1:]:
            logger.removeHandler(duplicate)
            duplicate.close()
    else:
        for existing in handlers:
            logger.removeHandler(existing)
            existing.close()
        handler = logging.StreamHandler(destination)
        setattr(handler, _HANDLER_MARKER, True)
        logger.addHandler(handler)

    handler.setLevel(logging.INFO)
    handler.setFormatter(JsonFormatter())
    return logger
