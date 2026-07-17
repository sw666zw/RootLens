import io
import json
import logging
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient as FastAPITestClient

from inventory_service.logging_config import (
    LOGGER_NAME,
    JsonFormatter,
    configure_logging,
)
from inventory_service.main import create_app


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
