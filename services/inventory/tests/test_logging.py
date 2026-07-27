import io
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient as FastAPITestClient
from opentelemetry.sdk.trace import TracerProvider

from inventory_service.logging_config import (
    LOGGER_NAME,
    FileLoggingSettings,
    JsonFormatter,
    configure_logging,
)
from inventory_service.main import create_app
from inventory_service.request_context import reset_request_id, set_request_id


def test_json_formatter_produces_required_base_fields() -> None:
    record = logging.LogRecord(
        name=LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="application_started",
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == LOGGER_NAME
    assert payload["message"] == "application_started"
    assert payload["service"] == "inventory"
    assert isinstance(payload["timestamp"], str)
    assert datetime.fromisoformat(payload["timestamp"]).utcoffset() == timedelta(0)


def test_request_log_contains_expected_fields() -> None:
    output = io.StringIO()
    configure_logging(output)
    client = FastAPITestClient(create_app())

    response = client.get("/health?include=ignored", headers={"X-Request-ID": "log-id"})

    payload = json.loads(output.getvalue())
    assert payload["message"] == "request_completed"
    assert payload["service"] == "inventory"
    assert payload["request_id"] == "log-id"
    assert payload["method"] == "GET"
    assert payload["path"] == "/health"
    assert payload["status_code"] == response.status_code
    assert isinstance(payload["duration_ms"], (int, float))
    assert payload["duration_ms"] >= 0


def test_repeated_configuration_does_not_duplicate_output() -> None:
    output = io.StringIO()

    logger = configure_logging(output)
    logger = configure_logging(output)
    logger.info("configured_once")

    assert len(output.getvalue().splitlines()) == 1


def test_repeated_application_creation_does_not_add_handlers() -> None:
    logger = configure_logging(io.StringIO())
    initial_handlers = list(logger.handlers)

    create_app()
    create_app()

    assert logger.handlers == initial_handlers


def test_failed_request_logs_exception_information_and_reraises() -> None:
    output = io.StringIO()
    configure_logging(output)
    application = create_app()

    @application.get("/failure")
    def failure() -> None:
        raise RuntimeError("test failure")

    client = FastAPITestClient(application)

    with pytest.raises(RuntimeError, match="test failure"):
        client.get("/failure", headers={"X-Request-ID": "failure-id"})

    payload = json.loads(output.getvalue())
    assert payload["message"] == "request_failed"
    assert payload["service"] == "inventory"
    assert payload["request_id"] == "failure-id"
    assert payload["method"] == "GET"
    assert payload["path"] == "/failure"
    assert payload["duration_ms"] >= 0
    assert "RuntimeError: test failure" in payload["exception"]


def file_logging(path: Path, *, enabled: bool = True) -> FileLoggingSettings:
    return FileLoggingSettings(enabled=enabled, path=path)


def read_json_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_enabled_file_logging_creates_parent_and_one_json_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "inventory.jsonl"
    logger = configure_logging(io.StringIO(), file_logging(path))

    logger.info("file_event")

    assert path.parent.is_dir()
    lines = read_json_lines(path)
    assert len(lines) == 1
    assert lines[0]["message"] == "file_event"


def test_file_and_console_logs_have_the_same_structured_fields(
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    path = tmp_path / "inventory.jsonl"
    logger = configure_logging(output, file_logging(path))

    logger.info(
        "inventory_reservation_succeeded",
        extra={
            "request_id": "same-fields",
            "sku": "LAPTOP-001",
            "requested_quantity": 2,
            "remaining_quantity": 8,
        },
    )

    console_payload = json.loads(output.getvalue())
    file_payload = read_json_lines(path)[0]
    assert file_payload == console_payload
    assert file_payload["request_id"] == "same-fields"
    assert file_payload["sku"] == "LAPTOP-001"
    assert file_payload["requested_quantity"] == 2
    assert file_payload["remaining_quantity"] == 8


def test_file_log_includes_active_trace_and_request_context(
    tmp_path: Path,
) -> None:
    path = tmp_path / "inventory.jsonl"
    logger = configure_logging(io.StringIO(), file_logging(path))
    provider = TracerProvider()
    tracer = provider.get_tracer(__name__)
    request_token = set_request_id("context-request-id")

    try:
        with tracer.start_as_current_span("file-log") as span:
            logger.info("correlated_file_event")
            context = span.get_span_context()
    finally:
        reset_request_id(request_token)
        provider.shutdown()

    payload = read_json_lines(path)[0]
    assert payload["request_id"] == "context-request-id"
    assert payload["trace_id"] == f"{context.trace_id:032x}"
    assert payload["span_id"] == f"{context.span_id:016x}"


def test_disabled_file_logging_does_not_create_file(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "inventory.jsonl"
    logger = configure_logging(io.StringIO(), file_logging(path, enabled=False))

    logger.info("console_only")

    assert not path.exists()
    assert not path.parent.exists()


def test_repeated_configuration_has_one_file_handler_and_one_output(
    tmp_path: Path,
) -> None:
    path = tmp_path / "inventory.jsonl"
    settings = file_logging(path)

    logger = configure_logging(io.StringIO(), settings)
    logger = configure_logging(file_settings=settings)
    logger.info("configured_once")

    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert len(read_json_lines(path)) == 1


def test_switching_file_paths_does_not_leak_handlers(tmp_path: Path) -> None:
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"

    logger = configure_logging(io.StringIO(), file_logging(first_path))
    logger.info("first_path")
    logger = configure_logging(file_settings=file_logging(second_path))
    logger.info("second_path")

    assert [entry["message"] for entry in read_json_lines(first_path)] == ["first_path"]
    assert [entry["message"] for entry in read_json_lines(second_path)] == [
        "second_path"
    ]
    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == second_path


def test_application_creation_with_file_logging_disabled_creates_no_file(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    path = tmp_path / "application" / "inventory.jsonl"
    monkeypatch.setenv("ROOTLENS_FILE_LOGGING_ENABLED", "false")
    monkeypatch.setenv("ROOTLENS_LOG_FILE_PATH", str(path))

    application = create_app()

    assert application is not None
    assert not path.exists()
