"""Stable, client-safe domain failures."""

from typing import Any


class DomainError(Exception):
    code = "conflict"
    status_code = 409
    default_message = "The requested operation conflicts with the current state."

    def __init__(
        self, message: str | None = None, *, details: dict[str, Any] | None = None
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(DomainError):
    code = "validation_error"
    status_code = 422
    default_message = "The request is invalid."


class UnauthenticatedError(DomainError):
    code = "unauthenticated"
    status_code = 401
    default_message = "Authentication is required."


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    status_code = 403
    default_message = "You do not have permission to perform this action."


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404
    default_message = "The requested resource was not found."


class ConflictError(DomainError):
    code = "conflict"
    status_code = 409


class StaleVersionError(ConflictError):
    code = "stale_version"
    default_message = "The record changed since it was loaded."


class DatabaseUnavailableError(DomainError):
    code = "database_unavailable"
    status_code = 503
    default_message = "Database is unavailable."
