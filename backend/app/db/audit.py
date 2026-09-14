"""Append-only audit writes that participate in the caller's transaction."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Column, DateTime, MetaData, Table, Text, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from backend.app.core.context import current_transaction_id

AUDIT_EVENT = Table(
    "audit_event",
    MetaData(),
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("actor_account_id", PG_UUID(as_uuid=True), nullable=False),
    Column("league_id", PG_UUID(as_uuid=True), nullable=False),
    Column("entity_type", Text()),
    Column("entity_id", PG_UUID(as_uuid=True)),
    Column("correlation_id", PG_UUID(as_uuid=True), nullable=False),
    Column("event_type", Text(), nullable=False),
    Column("reason", Text()),
    Column("before_state", JSONB()),
    Column("after_state", JSONB()),
    Column("occurred_at", DateTime(timezone=True)),
    schema="app",
)


class AuditWriter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def write(
        self,
        *,
        actor_account_id: UUID,
        league_id: UUID,
        event_type: str,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        reason: str | None = None,
        before_state: Mapping[str, Any] | None = None,
        after_state: Mapping[str, Any] | None = None,
    ) -> UUID:
        row = self.session.execute(
            insert(AUDIT_EVENT)
            .values(
                actor_account_id=actor_account_id,
                league_id=league_id,
                entity_type=entity_type,
                entity_id=entity_id,
                correlation_id=current_transaction_id(),
                event_type=event_type,
                reason=reason,
                before_state=dict(before_state) if before_state is not None else None,
                after_state=dict(after_state) if after_state is not None else None,
            )
            .returning(AUDIT_EVENT.c.id)
        ).scalar_one()
        return row

    def entity_history(
        self, *, league_id: UUID, entity_type: str, entity_id: UUID
    ) -> Sequence[RowMapping]:
        return self.session.execute(
            select(AUDIT_EVENT)
            .where(
                AUDIT_EVENT.c.league_id == league_id,
                AUDIT_EVENT.c.entity_type == entity_type,
                AUDIT_EVENT.c.entity_id == entity_id,
            )
            .order_by(AUDIT_EVENT.c.occurred_at, AUDIT_EVENT.c.id)
        ).mappings().all()

    def by_correlation_id(
        self, *, league_id: UUID, correlation_id: UUID
    ) -> Sequence[RowMapping]:
        return self.session.execute(
            select(AUDIT_EVENT)
            .where(
                AUDIT_EVENT.c.league_id == league_id,
                AUDIT_EVENT.c.correlation_id == correlation_id,
            )
            .order_by(AUDIT_EVENT.c.occurred_at, AUDIT_EVENT.c.id)
        ).mappings().all()
