from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from inventory_service.database import check_database_readiness

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Report that the Inventory Service is running."""
    return {"status": "ok", "service": "inventory"}


@router.get("/health/ready")
async def readiness(
    database_ready: Annotated[bool, Depends(check_database_readiness)],
) -> JSONResponse:
    """Report whether the Inventory Service can reach PostgreSQL."""
    if database_ready:
        return JSONResponse(
            content={
                "status": "ready",
                "service": "inventory",
                "database": "ok",
            }
        )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "not_ready",
            "service": "inventory",
            "database": "unavailable",
        },
    )
