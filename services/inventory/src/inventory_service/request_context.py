"""Request-scoped context available to Inventory Service application logs."""

from contextvars import ContextVar, Token

request_id_context: ContextVar[str | None] = ContextVar(
    "inventory_request_id",
    default=None,
)


def set_request_id(request_id: str) -> Token[str | None]:
    """Set the request ID for the current asynchronous context."""
    return request_id_context.set(request_id)


def get_request_id() -> str | None:
    """Return the request ID for the current asynchronous context, if any."""
    return request_id_context.get()


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the request ID context to its state before the request."""
    request_id_context.reset(token)
