"""Transaction boundary for domain services."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.core.context import reset_transaction_id, set_transaction_id


@contextmanager
def domain_transaction(session: Session) -> Iterator[None]:
    """Commit all domain/audit writes together, or roll them all back."""
    if session.in_transaction():
        raise RuntimeError("Domain services must own the outermost transaction")
    token = set_transaction_id(uuid4())
    try:
        with session.begin():
            yield
    finally:
        reset_transaction_id(token)
