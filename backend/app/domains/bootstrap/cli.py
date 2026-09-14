"""Operator command for provisioning the initial Survivor Fantasy league."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.db.session import SessionLocal
from backend.app.domains.bootstrap.service import (
    BootstrapConflictError,
    BootstrapRequest,
    BootstrapService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision or recover the initial system owner")
    parser.add_argument("--supabase-user-id", required=True, type=UUID)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--league-name", required=True)
    parser.add_argument("--season-name", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> int:
    args = build_parser().parse_args(argv)
    request = BootstrapRequest(
        supabase_user_id=args.supabase_user_id,
        email=args.email,
        display_name=args.display_name,
        league_name=args.league_name,
        season_name=args.season_name,
    )
    try:
        request = request.normalized()
        with session_factory() as db:
            result = BootstrapService().provision(db, request)
    except (BootstrapConflictError, ValueError) as error:
        raise SystemExit(f"bootstrap failed: {error}") from error
    print(f"system owner {result.account_id} provisioned for league {result.league_id}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    main()
