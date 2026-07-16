from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Report that the Inventory Service is running."""
    return {"status": "ok", "service": "inventory"}
