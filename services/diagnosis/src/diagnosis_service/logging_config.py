"""Structured JSON logging without secret or exception serialization."""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from diagnosis_service.request_context import get_request_id
from diagnosis_service.tracing import current_trace_ids

LOGGER_NAME = "diagnosis_service"
SERVICE_NAME = "diagnosis"
CONSOLE_MARKER = "_diagnosis_console_handler"
FILE_MARKER = "_diagnosis_file_handler"
FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "incident_id",
    "diagnosis_id",
    "explanation_id",
    "require_all_sources",
    "suspected_root_cause",
    "affected_service",
    "confidence",
    "telemetry_source_count",
    "partial_telemetry",
    "provider",
    "provider_status",
    "reason",
)


@dataclass(frozen=True)
class FileLoggingSettings:
    enabled: bool
    path: Path

    @classmethod
    def from_environment(cls) -> "FileLoggingSettings":
        raw = os.getenv("ROOTLENS_FILE_LOGGING_ENABLED", "false")
        return cls(
            raw.strip().lower() in {"1", "true", "yes", "on"},
            Path(
                os.getenv(
                    "ROOTLENS_DIAGNOSIS_LOG_FILE_PATH",
                    "runtime/logs/diagnosis.jsonl",
                )
            ),
        )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": SERVICE_NAME,
        }
        for field in FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        request_id = get_request_id()
        if request_id and "request_id" not in payload:
            payload["request_id"] = request_id
        trace_ids = current_trace_ids()
        if trace_ids:
            payload["trace_id"], payload["span_id"] = trace_ids
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    stream: TextIO | None = None,
    file_settings: FileLoggingSettings | None = None,
) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = JsonFormatter()
    destination = stream or sys.stderr
    consoles = [h for h in logger.handlers if getattr(h, CONSOLE_MARKER, False)]
    if consoles and (stream is None or consoles[0].stream is destination):
        console = consoles[0]
    else:
        for handler in consoles:
            logger.removeHandler(handler)
            handler.close()
        console = logging.StreamHandler(destination)
        setattr(console, CONSOLE_MARKER, True)
        logger.addHandler(console)
    console.setFormatter(formatter)

    settings = file_settings or FileLoggingSettings.from_environment()
    files = [h for h in logger.handlers if getattr(h, FILE_MARKER, False)]
    resolved = settings.path.expanduser().resolve()
    matching = [h for h in files if Path(h.baseFilename) == resolved]
    if settings.enabled and not matching:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(resolved, encoding="utf-8")
        setattr(handler, FILE_MARKER, True)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    for handler in files:
        if not settings.enabled or Path(handler.baseFilename) != resolved:
            logger.removeHandler(handler)
            handler.close()
    return logger
