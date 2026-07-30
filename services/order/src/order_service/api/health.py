"""Order Service liveness endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Report that the Order Service process is running."""
    return {"status": "ok", "service": "order"}
