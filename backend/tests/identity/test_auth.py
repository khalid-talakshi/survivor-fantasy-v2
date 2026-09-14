from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from backend.app.domains.identity.auth import AuthenticationError, SupabaseTokenVerifier

ISSUER = "https://project.supabase.co/auth/v1"
AUDIENCE = "authenticated"


def jwk(private_key: Any, algorithm: str, kid: str) -> dict[str, str]:
    converter = jwt.algorithms.get_default_algorithms()[algorithm]
    payload = converter.to_jwk(private_key.public_key())
    result = json.loads(payload)
    result.update({"kid": kid, "alg": algorithm, "use": "sig"})
    return result


def token(private_key: Any, algorithm: str, kid: str, **claims: object) -> str:
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "sub": str(uuid4()),
        "email": "User@Example.com",
    }
    payload.update(claims)
    return jwt.encode(payload, private_key, algorithm=algorithm, headers={"kid": kid})


@pytest.mark.parametrize(
    ("algorithm", "private_key"),
    [
        ("RS256", rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        ("ES256", ec.generate_private_key(ec.SECP256R1())),
    ],
)
def test_verifies_allowed_asymmetric_tokens(algorithm: str, private_key: Any) -> None:
    verifier = SupabaseTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_fetcher=lambda: {"keys": [jwk(private_key, algorithm, "primary")]},
    )

    identity = verifier.verify(token(private_key, algorithm, "primary"))

    assert identity.email == "User@Example.com"


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"iss": "https://other.example/auth/v1"},
        {"aud": "other"},
        {"sub": "not-a-uuid"},
        {"email": ""},
    ],
)
def test_rejects_bad_claims(claims: dict[str, object]) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = SupabaseTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_fetcher=lambda: {"keys": [jwk(private_key, "RS256", "primary")]},
    )

    with pytest.raises(AuthenticationError):
        verifier.verify(token(private_key, "RS256", "primary", **claims))


def test_rejects_tampered_and_forbidden_algorithms() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = SupabaseTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_fetcher=lambda: {"keys": [jwk(private_key, "RS256", "primary")]},
    )
    valid = token(private_key, "RS256", "primary")
    header, payload, signature = valid.split(".")

    with pytest.raises(AuthenticationError):
        verifier.verify(".".join((header, payload, signature[:-1] + "A")))
    with pytest.raises(AuthenticationError):
        verifier.verify(jwt.encode({"sub": str(uuid4())}, "x" * 32, algorithm="HS256"))


def test_rejects_missing_required_claim() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = SupabaseTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_fetcher=lambda: {"keys": [jwk(private_key, "RS256", "primary")]},
    )
    missing_email = token(private_key, "RS256", "primary")
    decoded = jwt.decode(missing_email, options={"verify_signature": False})
    del decoded["email"]
    missing_email = jwt.encode(decoded, private_key, algorithm="RS256", headers={"kid": "primary"})

    with pytest.raises(AuthenticationError):
        verifier.verify(missing_email)


def test_cache_reuses_keys_and_refreshes_for_rotated_kid() -> None:
    first = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rotated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    documents = [
        {"keys": [jwk(first, "RS256", "first")]},
        {"keys": [jwk(first, "RS256", "first"), jwk(rotated, "RS256", "rotated")]},
    ]
    calls = 0

    def fetch() -> dict[str, object]:
        nonlocal calls
        result = documents[min(calls, len(documents) - 1)]
        calls += 1
        return result

    verifier = SupabaseTokenVerifier(
        issuer=ISSUER, audience=AUDIENCE, jwks_fetcher=fetch, cache_seconds=600
    )

    verifier.verify(token(first, "RS256", "first"))
    verifier.verify(token(first, "RS256", "first"))
    verifier.verify(token(rotated, "RS256", "rotated"))

    assert calls == 2


def test_metadata_does_not_affect_verified_identity() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = uuid4()
    verifier = SupabaseTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_fetcher=lambda: {"keys": [jwk(private_key, "RS256", "primary")]},
    )

    identity = verifier.verify(
        token(
            private_key,
            "RS256",
            "primary",
            sub=str(subject),
            user_metadata={"is_system_owner": True, "is_commissioner": True},
            app_metadata={"role": "service_role"},
        )
    )

    assert identity.supabase_user_id == subject
    assert identity.email == "User@Example.com"
