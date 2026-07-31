"""Idempotent Order creation behavior without external services."""

import concurrent.futures
import threading
from typing import Any

import httpx
import pytest
from test_support.order import (
    InMemoryOrdersRepository,
    make_client,
    sample_values,
    scrape,
    successful_inventory,
)

from order_service.idempotency import request_fingerprint
from order_service.repositories import orders


class FailingFinalRepository(InMemoryOrdersRepository):
    async def change_status(self, *args: object, **kwargs: object) -> None:
        raise orders.OrderPersistenceError


def test_unkeyed_requests_remain_separate_attempts() -> None:
    repository = InMemoryOrdersRepository()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return successful_inventory(request)

    with make_client(handler, repository=repository) as client:
        first = client.post("/orders", json={"sku": "SKU-001", "quantity": 1})
        second = client.post("/orders", json={"sku": "SKU-001", "quantity": 1})

    assert first.status_code == second.status_code == 201
    assert first.json()["order_id"] != second.json()["order_id"]
    assert len(repository.orders) == 2
    assert calls == 2


@pytest.mark.parametrize(
    ("key", "detail"),
    [
        ("   ", "Idempotency-Key must not be blank."),
        ("x" * 256, "Idempotency-Key must not exceed 255 characters."),
    ],
)
def test_invalid_idempotency_key_is_exact(key: str, detail: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with make_client(handler) as client:
        response = client.post(
            "/orders",
            headers={"Idempotency-Key": key},
            json={"sku": "SKU-001", "quantity": 1},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": detail}
    assert calls == 0


def test_request_fingerprint_uses_normalized_fields_only() -> None:
    normalized = request_fingerprint("SKU-001", 2)
    assert normalized == request_fingerprint("SKU-001", 2)
    assert normalized != request_fingerprint("SKU-002", 2)
    assert normalized != request_fingerprint("SKU-001", 3)
    assert len(normalized) == 64
    assert normalized == normalized.lower()


def test_new_keyed_request_stores_claim_before_inventory() -> None:
    repository = InMemoryOrdersRepository()

    def handler(_: httpx.Request) -> httpx.Response:
        persisted = next(iter(repository.orders.values()))
        assert repository.events == [("persist", "pending")]
        assert persisted.idempotency_key == "Client-Key"
        assert persisted.request_fingerprint == request_fingerprint("SKU-001", 1)
        return httpx.Response(
            200,
            json={
                "sku": "SKU-001",
                "reserved_quantity": 1,
                "remaining_quantity": 4,
            },
        )

    with make_client(handler, repository=repository) as client:
        response = client.post(
            "/orders",
            headers={"Idempotency-Key": "  Client-Key  "},
            json={"sku": " SKU-001 ", "quantity": 1},
        )

    assert response.status_code == 201
    assert "Idempotency-Replayed" not in response.headers


def test_confirmed_replay_returns_stored_response_without_inventory() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return successful_inventory(request)

    with make_client(handler) as client:
        first = client.post(
            "/orders",
            headers={"Idempotency-Key": "confirmed-key"},
            json={"sku": " SKU-001 ", "quantity": 1},
        )
        replay = client.post(
            "/orders",
            headers={"Idempotency-Key": "confirmed-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )

    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert calls == 1


@pytest.mark.parametrize(
    ("inventory_status", "expected_status", "expected_body"),
    [
        (404, 404, {"detail": "Inventory item not found."}),
        (409, 409, {"detail": "Insufficient inventory available."}),
        (500, 503, {"detail": "Inventory service unavailable."}),
    ],
)
def test_terminal_failure_replay_is_exact_and_does_not_call_inventory(
    inventory_status: int,
    expected_status: int,
    expected_body: dict[str, str],
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(inventory_status)

    with make_client(handler) as client:
        first = client.post(
            "/orders",
            headers={"Idempotency-Key": "terminal-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )
        replay = client.post(
            "/orders",
            headers={"Idempotency-Key": "terminal-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )

    assert first.status_code == replay.status_code == expected_status
    assert replay.json() == expected_body
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert calls == 1


def test_pending_repeat_has_retry_after_and_no_replay_header() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return successful_inventory(request)

    repository = FailingFinalRepository()
    with make_client(handler, repository=repository) as client:
        first = client.post(
            "/orders",
            headers={"Idempotency-Key": "pending-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )
        repeat = client.post(
            "/orders",
            headers={"Idempotency-Key": "pending-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )

    assert first.status_code == 503
    assert repeat.status_code == 409
    assert repeat.json() == {
        "detail": "An order with this idempotency key is still being processed."
    }
    assert repeat.headers["Retry-After"] == "1"
    assert "Idempotency-Replayed" not in repeat.headers
    assert calls == 1


@pytest.mark.parametrize(
    "changed_payload",
    [
        {"sku": "SKU-002", "quantity": 1},
        {"sku": "SKU-001", "quantity": 2},
    ],
)
def test_key_reuse_with_changed_payload_is_exact(
    changed_payload: dict[str, object],
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return successful_inventory(request)

    with make_client(handler) as client:
        client.post(
            "/orders",
            headers={"Idempotency-Key": "same-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )
        conflict = client.post(
            "/orders",
            headers={"Idempotency-Key": "same-key"},
            json=changed_payload,
        )

    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": "Idempotency key was already used with a different request."
    }
    assert calls == 1


def test_concurrent_duplicates_cannot_both_call_inventory() -> None:
    entered_inventory = threading.Event()
    release_inventory = threading.Event()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        entered_inventory.set()
        assert release_inventory.wait(timeout=10)
        return successful_inventory(request)

    repository = InMemoryOrdersRepository()
    with (
        make_client(handler, repository=repository) as first_client,
        make_client(handler, repository=repository) as second_client,
    ):

        def post(client: Any) -> httpx.Response:
            return client.post(
                "/orders",
                headers={"Idempotency-Key": "racing-key"},
                json={"sku": "SKU-001", "quantity": 1},
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(post, first_client)
            assert entered_inventory.wait(timeout=2)
            second = executor.submit(post, second_client)
            second_response = second.result(timeout=5)
            release_inventory.set()
            first_response = first.result(timeout=5)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.headers["Retry-After"] == "1"
    assert calls == 1


def test_idempotency_metrics_use_only_bounded_outcomes() -> None:
    repository = FailingFinalRepository()
    with make_client(successful_inventory, repository=repository) as client:
        client.post(
            "/orders",
            headers={"Idempotency-Key": "metric-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )
        client.post(
            "/orders",
            headers={"Idempotency-Key": "metric-key"},
            json={"sku": "SKU-001", "quantity": 1},
        )
        client.post(
            "/orders",
            headers={"Idempotency-Key": "metric-key"},
            json={"sku": "SKU-002", "quantity": 1},
        )
        exposition = scrape(client)

    for outcome in ("claimed", "in_progress", "payload_mismatch"):
        assert sample_values(
            exposition,
            "rootlens_order_idempotency_events_total",
            {"outcome": outcome},
        ) == [1.0]
    assert "metric-key" not in exposition


def test_completed_replay_increments_replayed_metric() -> None:
    with make_client(successful_inventory) as client:
        for _ in range(2):
            client.post(
                "/orders",
                headers={"Idempotency-Key": "replayed-metric-key"},
                json={"sku": "SKU-001", "quantity": 1},
            )
        exposition = scrape(client)

    assert sample_values(
        exposition,
        "rootlens_order_idempotency_events_total",
        {"outcome": "claimed"},
    ) == [1.0]
    assert sample_values(
        exposition,
        "rootlens_order_idempotency_events_total",
        {"outcome": "replayed"},
    ) == [1.0]
