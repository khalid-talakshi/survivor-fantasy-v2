"""Explicitly league-scoped SQLAlchemy Core repository helpers."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Select, Table, and_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from backend.app.core.errors import StaleVersionError


class LeagueRepository:
    """Queries a single league only; callers cannot issue opaque-ID lookups."""

    def __init__(self, session: Session, table: Table, league_id: UUID) -> None:
        if "league_id" not in table.c:
            raise ValueError(f"{table.fullname} is not a league-scoped table")
        self.session = session
        self.table = table
        self.league_id = league_id

    def select(self) -> Select[tuple[Any, ...]]:
        return select(self.table).where(self.table.c.league_id == self.league_id)

    def active(self) -> Select[tuple[Any, ...]]:
        statement = self.select()
        if "deleted_at" in self.table.c:
            statement = statement.where(self.table.c.deleted_at.is_(None))
        return statement

    def get(
        self, record_id: UUID, *, active: bool = False, lock: bool = False
    ) -> RowMapping | None:
        statement = self.active() if active else self.select()
        statement = statement.where(self.table.c.id == record_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.execute(statement).mappings().one_or_none()

    def update_versioned(
        self, record_id: UUID, expected_version: int, values: Mapping[str, Any]
    ) -> RowMapping:
        if "version" not in self.table.c:
            raise ValueError(f"{self.table.fullname} does not support optimistic concurrency")
        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        immutable_columns = {"id", "league_id", "version"}
        forbidden_columns = immutable_columns.intersection(values)
        if forbidden_columns:
            names = ", ".join(sorted(forbidden_columns))
            raise ValueError(f"Versioned updates cannot modify {names}")
        statement = (
            update(self.table)
            .where(
                and_(
                    self.table.c.league_id == self.league_id,
                    self.table.c.id == record_id,
                    self.table.c.version == expected_version,
                )
            )
            .values(**dict(values), version=self.table.c.version + 1)
            .returning(self.table)
        )
        row = self.session.execute(statement).mappings().one_or_none()
        if row is None:
            raise StaleVersionError()
        return row
