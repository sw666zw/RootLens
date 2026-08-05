"""Request-scoped correlation context."""

from contextvars import ContextVar, Token

request_id_context: ContextVar[str | None] = ContextVar(
    "diagnosis_request_id", default=None
)


def set_request_id(request_id: str) -> Token[str | None]:
    return request_id_context.set(request_id)


def get_request_id() -> str | None:
    return request_id_context.get()


def reset_request_id(token: Token[str | None]) -> None:
    request_id_context.reset(token)
