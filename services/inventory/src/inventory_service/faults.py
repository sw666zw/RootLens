"""Development-only, application-scoped reservation fault injection."""

import asyncio
import os
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReservationFailureMode(StrEnum):
    """Supported reservation failure behavior."""

    NONE = "none"
    SERVICE_UNAVAILABLE = "service_unavailable"


class ReservationFault(BaseModel):
    """Validated reservation fault configuration."""

    model_config = ConfigDict(frozen=True)

    delay_ms: int = Field(default=0, ge=0, le=10_000, strict=True)
    failure_mode: ReservationFailureMode = ReservationFailureMode.NONE


class ReservationFaultController:
    """Concurrency-safe in-memory fault state owned by one application."""

    def __init__(self, initial: ReservationFault | None = None) -> None:
        self._state = initial or ReservationFault()
        self._lock = asyncio.Lock()

    async def read(self) -> ReservationFault:
        """Return the current immutable configuration."""
        async with self._lock:
            return self._state

    async def update(self, configuration: ReservationFault) -> ReservationFault:
        """Replace the complete current configuration."""
        async with self._lock:
            self._state = configuration
            return self._state

    async def reset(self) -> ReservationFault:
        """Restore the disabled reservation behavior."""
        return await self.update(ReservationFault())


def fault_injection_enabled() -> bool:
    """Return whether development-only endpoints should be registered."""
    value = os.getenv("ROOTLENS_FAULT_INJECTION_ENABLED", "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}
