"""Safe, deterministic helpers for idempotent order creation."""

import hashlib
import json


def request_fingerprint(sku: str, quantity: int) -> str:
    """Return a stable SHA-256 fingerprint for normalized order fields."""
    serialized = json.dumps(
        {"quantity": quantity, "sku": sku},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def idempotency_key_hash(idempotency_key: str) -> str:
    """Return a safe log representation of an idempotency key."""
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
