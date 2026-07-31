"""Order Service liveness and readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from order_service.database import check_database_readiness

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Report that the Order Service process is running."""
    return {"status": "ok", "service": "order"}


@router.get("/health/ready")
async def readiness(
    database_ready: Annotated[bool, Depends(check_database_readiness)],
) -> JSONResponse:
    """Report whether the Order Service can reach its PostgreSQL database."""
    if database_ready:
        return JSONResponse(
            content={"status": "ready", "service": "order", "database": "ok"}
        )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "not_ready",
            "service": "order",
            "database": "unavailable",
        },
    )
