from uuid import uuid4

import pytest

from backend.app.domains.bootstrap.cli import build_parser, main


def test_cli_requires_all_bootstrap_parameters() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args([])
    assert error.value.code == 2


def test_cli_rejects_invalid_supabase_user_id() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(
            [
                "--supabase-user-id",
                "not-a-uuid",
                "--email",
                "owner@example.com",
                "--display-name",
                "Owner",
                "--league-name",
                "League",
                "--season-name",
                "Season",
            ]
        )
    assert error.value.code == 2


def test_cli_rejects_blank_required_text_before_writing() -> None:
    with pytest.raises(SystemExit, match="display name must not be blank"):
        main(
            [
                "--supabase-user-id",
                str(uuid4()),
                "--email",
                "owner@example.com",
                "--display-name",
                " ",
                "--league-name",
                "League",
                "--season-name",
                "Season",
            ],
            session_factory=lambda: pytest.fail("blank input must not open a database session"),
        )


def test_cli_rejects_blank_email_before_writing() -> None:
    with pytest.raises(SystemExit, match="email must not be blank"):
        main(
            [
                "--supabase-user-id",
                str(uuid4()),
                "--email",
                " ",
                "--display-name",
                "Owner",
                "--league-name",
                "League",
                "--season-name",
                "Season",
            ],
            session_factory=lambda: pytest.fail("blank input must not open a database session"),
        )
