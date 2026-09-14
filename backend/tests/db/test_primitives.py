from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, Table, create_engine, insert, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from backend.app.core.context import current_transaction_id
from backend.app.core.errors import StaleVersionError
from backend.app.db.audit import AuditWriter
from backend.app.db.repositories import LeagueRepository
from backend.app.db.transactions import domain_transaction


def _table(session: Session, name: str) -> Table:
    return Table(name, MetaData(), schema="app", autoload_with=session.bind)


@pytest.fixture
def session(empty_database: URL) -> Session:
    engine = create_engine(empty_database.set(drivername="postgresql+psycopg"))
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


@pytest.fixture
def league_data(session: Session, migrated_database: object) -> tuple[UUID, UUID, UUID, UUID]:
    account = _table(session, "account")
    league = _table(session, "league")
    bucket = _table(session, "bucket")
    actor_id, league_id, other_league_id, bucket_id = (uuid4(), uuid4(), uuid4(), uuid4())
    with session.begin():
        session.execute(
            insert(account).values(
                id=actor_id,
                supabase_user_id=uuid4(),
                email="commissioner@example.com",
                display_name="Commissioner",
            )
        )
        session.execute(
            insert(league).values(id=league_id, name="Primary", season_name="Season 1")
        )
        session.execute(
            insert(league).values(id=other_league_id, name="Other", season_name="Season 2")
        )
        session.execute(
            insert(bucket).values(
                id=bucket_id, league_id=league_id, name="Tribe", display_order=0
            )
        )
    return actor_id, league_id, other_league_id, bucket_id


def test_audit_write_and_domain_change_commit_atomically(
    session: Session, league_data: tuple[UUID, UUID, UUID, UUID]
) -> None:
    actor_id, league_id, other_league_id, bucket_id = league_data
    bucket = _table(session, "bucket")
    audit = AuditWriter(session)

    with domain_transaction(session):
        correlation_id = current_transaction_id()
        session.execute(bucket.update().where(bucket.c.id == bucket_id).values(name="Merged"))
        audit.write(
            actor_account_id=actor_id,
            league_id=league_id,
            event_type="bucket.updated",
            entity_type="bucket",
            entity_id=bucket_id,
            before_state={"name": "Tribe"},
            after_state={"name": "Merged"},
        )

    bucket_name = session.execute(
        select(bucket.c.name).where(bucket.c.id == bucket_id)
    ).scalar_one()
    assert bucket_name == "Merged"
    history = audit.entity_history(
        league_id=league_id, entity_type="bucket", entity_id=bucket_id
    )
    assert len(history) == 1
    assert history[0]["correlation_id"] == correlation_id
    assert audit.by_correlation_id(league_id=league_id, correlation_id=correlation_id)[0][
        "id"
    ] == history[0]["id"]
    assert audit.by_correlation_id(league_id=other_league_id, correlation_id=correlation_id) == []


def test_domain_transaction_rolls_back_audit_and_domain_change(
    session: Session, league_data: tuple[UUID, UUID, UUID, UUID]
) -> None:
    actor_id, league_id, _, bucket_id = league_data
    bucket = _table(session, "bucket")
    audit = AuditWriter(session)

    with pytest.raises(RuntimeError, match="force rollback"), domain_transaction(session):
        session.execute(bucket.update().where(bucket.c.id == bucket_id).values(name="Discarded"))
        audit.write(
            actor_account_id=actor_id,
            league_id=league_id,
            event_type="bucket.updated",
            entity_type="bucket",
            entity_id=bucket_id,
        )
        raise RuntimeError("force rollback")

    bucket_name = session.execute(
        select(bucket.c.name).where(bucket.c.id == bucket_id)
    ).scalar_one()
    assert bucket_name == "Tribe"
    assert (
        audit.entity_history(league_id=league_id, entity_type="bucket", entity_id=bucket_id)
        == []
    )


def test_audit_history_is_bounded_and_cursor_paginated(
    session: Session, league_data: tuple[UUID, UUID, UUID, UUID]
) -> None:
    actor_id, league_id, _, bucket_id = league_data
    audit = AuditWriter(session)

    with domain_transaction(session):
        correlation_id = current_transaction_id()
        for event_type in ("bucket.created", "bucket.updated", "bucket.deleted"):
            audit.write(
                actor_account_id=actor_id,
                league_id=league_id,
                event_type=event_type,
                entity_type="bucket",
                entity_id=bucket_id,
            )

    first_page = audit.entity_history(
        league_id=league_id, entity_type="bucket", entity_id=bucket_id, limit=2
    )
    cursor = (first_page[-1]["occurred_at"], first_page[-1]["id"])
    second_page = audit.entity_history(
        league_id=league_id,
        entity_type="bucket",
        entity_id=bucket_id,
        limit=2,
        before=cursor,
    )

    assert len(first_page) == 2
    assert len(second_page) == 1
    assert {row["id"] for row in first_page}.isdisjoint(row["id"] for row in second_page)
    assert len(audit.by_correlation_id(league_id=league_id, correlation_id=correlation_id)) == 3
    with pytest.raises(ValueError, match="limit"):
        audit.entity_history(
            league_id=league_id, entity_type="bucket", entity_id=bucket_id, limit=101
        )


def test_league_repository_enforces_scope_and_optimistic_version(
    session: Session, league_data: tuple[UUID, UUID, UUID, UUID]
) -> None:
    _, league_id, other_league_id, bucket_id = league_data
    bucket = _table(session, "bucket")
    repository = LeagueRepository(session, bucket, league_id)
    other_repository = LeagueRepository(session, bucket, other_league_id)

    with domain_transaction(session):
        assert repository.get(bucket_id)["version"] == 1
        updated = repository.update_versioned(bucket_id, 1, {"name": "Updated"})
    assert updated["version"] == 2
    with domain_transaction(session):
        assert other_repository.get(bucket_id) is None
    with pytest.raises(ValueError, match="league_id"):
        repository.update_versioned(bucket_id, 2, {"league_id": other_league_id})

    with domain_transaction(session), pytest.raises(StaleVersionError):
        repository.update_versioned(bucket_id, 1, {"name": "Stale"})
    with domain_transaction(session):
        assert repository.get(bucket_id)["name"] == "Updated"

    with domain_transaction(session), pytest.raises(StaleVersionError):
        other_repository.update_versioned(bucket_id, 2, {"name": "Foreign"})
    with domain_transaction(session):
        assert repository.get(bucket_id)["name"] == "Updated"
