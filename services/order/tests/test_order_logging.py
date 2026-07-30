"""Structured application logging tests."""

import io
import json
import logging
from pathlib import Path

import httpx
import pytest

from helpers import make_client, successful_inventory
from order_service.logging_config import (
    FileLoggingSettings,
    configure_logging,
)


def parsed_lines(output: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize(
    ("status_code", "message", "level", "reason"),
    [
        (404, "order_creation_rejected", "WARNING", "item_not_found"),
        (
            409,
            "order_creation_rejected",
            "WARNING",
            "insufficient_inventory",
        ),
        (500, "order_creation_failed", "ERROR", "inventory_unavailable"),
        (
            422,
            "order_creation_failed",
            "ERROR",
            "inventory_invalid_response",
        ),
    ],
)
def test_rejection_and_failure_logs_have_safe_fields(
    status_code: int,
    message: str,
    level: str,
    reason: str,
) -> None:
    output = io.StringIO()
    configure_logging(output)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="downstream-password")

    with make_client(handler) as client:
        client.post(
            "/orders",
            headers={"X-Request-ID": "log-request"},
            json={"sku": "SKU-001", "quantity": 1},
        )

    event = next(item for item in parsed_lines(output) if item["message"] == message)
    assert event["level"] == level
    assert event["service"] == "order"
    assert event["request_id"] == "log-request"
    assert event["sku"] == "SKU-001"
    assert event["quantity"] == 1
    assert event["reason"] == reason
    assert "downstream-password" not in output.getvalue()


def test_success_log_has_required_fields() -> None:
    output = io.StringIO()
    configure_logging(output)
    with make_client(successful_inventory) as client:
        client.post(
            "/orders",
            headers={"X-Request-ID": "success-request"},
            json={"sku": "SKU-001", "quantity": 1},
        )

    event = next(
        item
        for item in parsed_lines(output)
        if item["message"] == "order_creation_succeeded"
    )
    assert event["request_id"] == "success-request"
    assert event["sku"] == "SKU-001"
    assert event["quantity"] == 1
    assert event["remaining_inventory"] == 8
    assert "order_id" in event


def test_file_logging_uses_temp_directory_without_duplicate_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "order.jsonl"
    settings = FileLoggingSettings(enabled=True, path=path)
    logger = configure_logging(io.StringIO(), settings)
    logger = configure_logging(file_settings=settings)
    logger.info("one_line")

    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"] == "one_line"
    assert (
        len([item for item in logger.handlers if isinstance(item, logging.FileHandler)])
        == 1
    )
