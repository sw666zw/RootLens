"""Environment-driven runtime configuration for the Order Service."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_INVENTORY_SERVICE_URL = "http://localhost:8000"


def _port_from_environment() -> int:
    raw_value = os.getenv("ORDER_SERVICE_PORT", "8001")
    try:
        port = int(raw_value)
    except ValueError as error:
        raise ValueError("ORDER_SERVICE_PORT must be an integer.") from error
    if not 1 <= port <= 65535:
        raise ValueError("ORDER_SERVICE_PORT must be between 1 and 65535.")
    return port


def _inventory_url_from_environment() -> str:
    value = os.getenv("INVENTORY_SERVICE_URL", DEFAULT_INVENTORY_SERVICE_URL).strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("INVENTORY_SERVICE_URL must be an absolute HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("INVENTORY_SERVICE_URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError(
            "INVENTORY_SERVICE_URL must not contain a query string or fragment."
        )
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    """Validated Order Service settings."""

    host: str
    port: int
    inventory_service_url: str

    @classmethod
    def from_environment(cls) -> "Settings":
        """Load and validate configuration without a dotenv dependency."""
        host = os.getenv("ORDER_SERVICE_HOST", "0.0.0.0").strip()
        if not host:
            raise ValueError("ORDER_SERVICE_HOST must not be blank.")
        return cls(
            host=host,
            port=_port_from_environment(),
            inventory_service_url=_inventory_url_from_environment(),
        )
