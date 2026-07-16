from fastapi import FastAPI

from inventory_service.api.health import router as health_router


def create_app() -> FastAPI:
    """Create and configure the Inventory Service application."""
    application = FastAPI(
        title="RootLens Inventory Service",
        version="0.1.0",
    )
    application.include_router(health_router)
    return application


app = create_app()
