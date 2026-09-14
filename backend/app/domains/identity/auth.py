from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import UUID

import httpx
import jwt
from jwt import InvalidTokenError

ALLOWED_ALGORITHMS = ("ES256", "RS256")


class AuthenticationError(Exception):
    """Raised when a bearer token cannot establish an application identity."""


@dataclass(frozen=True)
class VerifiedIdentity:
    supabase_user_id: UUID
    email: str


JwksFetcher = Callable[[], Mapping[str, object]]


def fetch_jwks(url: str) -> Mapping[str, object]:
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AuthenticationError from None
    return payload


class SupabaseTokenVerifier:
    """Verify Supabase access tokens using a short-lived, rotation-aware JWKS cache."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_fetcher: JwksFetcher,
        cache_seconds: int = 600,
        forced_refresh_cooldown_seconds: int = 30,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_fetcher = jwks_fetcher
        self.cache_seconds = cache_seconds
        self.forced_refresh_cooldown_seconds = forced_refresh_cooldown_seconds
        self.clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires_at = 0.0
        self._next_forced_refresh_at: float | None = None
        self._lock = Lock()

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if algorithm not in ALLOWED_ALGORITHMS or not isinstance(kid, str) or not kid:
                raise AuthenticationError
            key = self._get_key(kid, algorithm)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=list(ALLOWED_ALGORITHMS),
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "sub", "email"]},
            )
            subject = claims["sub"]
            email = claims["email"]
            if not isinstance(subject, str) or not isinstance(email, str) or not email.strip():
                raise AuthenticationError
            return VerifiedIdentity(supabase_user_id=UUID(subject), email=email)
        except (AuthenticationError, InvalidTokenError, ValueError, TypeError, KeyError):
            raise AuthenticationError from None

    def _get_key(self, kid: str, algorithm: str) -> jwt.PyJWK:
        with self._lock:
            now = self.clock()
            refreshed_expired_cache = now >= self._expires_at
            if refreshed_expired_cache:
                self._refresh()
            key = self._keys.get(kid)
            if (
                key is None
                and not refreshed_expired_cache
                and (self._next_forced_refresh_at is None or now >= self._next_forced_refresh_at)
            ):
                # A fresh document may contain a just-rotated signing key.
                self._refresh()
                self._next_forced_refresh_at = now + self.forced_refresh_cooldown_seconds
                key = self._keys.get(kid)
            if key is None:
                raise AuthenticationError
            if key.algorithm_name != algorithm:
                raise AuthenticationError
            return key

    def _refresh(self) -> None:
        try:
            payload = self.jwks_fetcher()
            keys = payload.get("keys")
            if not isinstance(keys, list):
                raise AuthenticationError
            parsed = {
                key_id: jwt.PyJWK.from_dict(key)
                for key in keys
                if isinstance(key, dict)
                and isinstance((key_id := key.get("kid")), str)
                and key.get("alg") in ALLOWED_ALGORITHMS
                and key.get("kty") in {"EC", "RSA"}
            }
            if not parsed:
                raise AuthenticationError
        except (AuthenticationError, httpx.HTTPError, jwt.PyJWTError, TypeError, ValueError):
            raise AuthenticationError from None
        self._keys = parsed
        self._expires_at = self.clock() + self.cache_seconds
