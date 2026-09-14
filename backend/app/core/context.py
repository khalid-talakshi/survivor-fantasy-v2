"""Request and transaction-scoped correlation identifiers."""

from contextvars import ContextVar, Token
from uuid import UUID, uuid4

request_id: ContextVar[UUID | None] = ContextVar("request_id", default=None)
transaction_id: ContextVar[UUID | None] = ContextVar("transaction_id", default=None)


def current_request_id() -> UUID:
    """Return the current request identifier, creating one for non-HTTP callers."""
    value = request_id.get()
    if value is None:
        value = uuid4()
        request_id.set(value)
    return value


def current_transaction_id() -> UUID:
    value = transaction_id.get()
    if value is None:
        raise RuntimeError("A domain transaction is required for this operation")
    return value


def set_request_id(value: UUID) -> Token[UUID | None]:
    return request_id.set(value)


def reset_request_id(token: Token[UUID | None]) -> None:
    request_id.reset(token)


def set_transaction_id(value: UUID) -> Token[UUID | None]:
    return transaction_id.set(value)


def reset_transaction_id(token: Token[UUID | None]) -> None:
    transaction_id.reset(token)
