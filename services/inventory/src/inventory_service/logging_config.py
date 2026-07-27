"""Structured logging configuration for the Inventory Service."""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from inventory_service.request_context import get_request_id
from inventory_service.tracing import current_trace_ids

SERVICE_NAME = "inventory"
LOGGER_NAME = "inventory_service"
DEFAULT_LOG_FILE_PATH = Path("runtime/logs/inventory.jsonl")
_CONSOLE_HANDLER_MARKER = "_inventory_json_console_handler"
_FILE_HANDLER_MARKER = "_inventory_json_file_handler"
_STRUCTURED_FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "sku",
    "requested_quantity",
    "remaining_quantity",
    "reason",
)


def _environment_boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FileLoggingSettings:
    """Environment-driven settings for the optional JSON-lines file output."""

    enabled: bool
    path: Path

    @classmethod
    def from_environment(cls) -> "FileLoggingSettings":
        """Load file logging settings without requiring dotenv at runtime."""
        return cls(
            enabled=_environment_boolean("ROOTLENS_FILE_LOGGING_ENABLED", False),
            path=Path(os.getenv("ROOTLENS_LOG_FILE_PATH", str(DEFAULT_LOG_FILE_PATH))),
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

        for field in _STRUCTURED_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        request_id = get_request_id()
        if request_id is not None and "request_id" not in payload:
            payload["request_id"] = request_id

        trace_ids = current_trace_ids()
        if trace_ids is not None:
            payload["trace_id"], payload["span_id"] = trace_ids

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


class JsonLinesFileHandler(logging.FileHandler):
    """Flush and close after each record so host-mounted containers see appends."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        finally:
            if self.stream is not None:
                self.stream.close()
                self.stream = None


def _configure_console_handler(
    logger: logging.Logger,
    stream: TextIO | None,
    formatter: logging.Formatter,
) -> None:
    handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, _CONSOLE_HANDLER_MARKER, False)
    ]
    destination = stream if stream is not None else sys.stderr

    if handlers and (stream is None or handlers[0].stream is destination):
        handler = handlers[0]
        duplicates = handlers[1:]
    else:
        duplicates = handlers
        handler = logging.StreamHandler(destination)
        setattr(handler, _CONSOLE_HANDLER_MARKER, True)
        logger.addHandler(handler)

    for duplicate in duplicates:
        logger.removeHandler(duplicate)
        duplicate.close()

    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)


def _configure_file_handler(
    logger: logging.Logger,
    settings: FileLoggingSettings,
    formatter: logging.Formatter,
) -> None:
    handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, _FILE_HANDLER_MARKER, False)
    ]
    requested_path = settings.path.expanduser().resolve()

    if not settings.enabled:
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()
        return

    requested_path.parent.mkdir(parents=True, exist_ok=True)
    matching = [
        handler for handler in handlers if Path(handler.baseFilename) == requested_path
    ]

    if matching:
        handler = matching[0]
        duplicates = [candidate for candidate in handlers if candidate is not handler]
    else:
        duplicates = handlers
        handler = JsonLinesFileHandler(requested_path, encoding="utf-8")
        setattr(handler, _FILE_HANDLER_MARKER, True)
        logger.addHandler(handler)

    for duplicate in duplicates:
        logger.removeHandler(duplicate)
        duplicate.close()

    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)


def configure_logging(
    stream: TextIO | None = None,
    file_settings: FileLoggingSettings | None = None,
) -> logging.Logger:
    """Configure the application logger without accumulating handlers."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = JsonFormatter()
    _configure_console_handler(logger, stream, formatter)
    _configure_file_handler(
        logger,
        file_settings or FileLoggingSettings.from_environment(),
        formatter,
    )
    return logger
