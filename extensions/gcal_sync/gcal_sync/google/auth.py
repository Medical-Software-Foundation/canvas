"""Google service-account auth with domain-wide delegation (spec §3).

Because every provider is in one Google Workspace org, we skip 3-legged OAuth entirely. The
plugin holds a single service-account key and, for each provider, mints a short-lived JWT that
*impersonates* that provider (``sub = provider@example.com``) and exchanges it for an access token
via the JWT-bearer grant. No per-user consent screens and no refresh tokens to store or rotate.

Access tokens are cached per impersonated subject for just under their lifetime so a burst of
appointment events doesn't mint a token per event.
"""

import json

import arrow
import jwt

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils.http import Http
from logger import log

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# Assertions are valid for an hour (Google's max); tokens come back with ~3600s lifetime.
_ASSERTION_TTL_SECONDS = 3600
# Re-mint a little before expiry to avoid using a token that dies mid-request.
_TOKEN_CACHE_SAFETY_MARGIN_SECONDS = 120


class GoogleAuthError(RuntimeError):
    """Raised when the service account is misconfigured or the token exchange fails.

    This is deliberately a hard error rather than a silent ``None`` — a missing or invalid
    service-account key must surface, not fail open (CLAUDE.md: fail closed).
    """


def parse_service_account(secret_value: str | None) -> dict:
    """Parse and validate the ``GOOGLE_SERVICE_ACCOUNT_JSON`` secret.

    Fails closed: a missing secret, malformed JSON, or a key without the fields we need to sign an
    assertion all raise ``GoogleAuthError`` rather than returning a partial config.
    """
    if not secret_value or not secret_value.strip():
        raise GoogleAuthError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    try:
        data: dict = json.loads(secret_value)
    except json.JSONDecodeError as exc:
        raise GoogleAuthError(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}") from exc

    for required in ("client_email", "private_key"):
        if not data.get(required):
            raise GoogleAuthError(f"service account JSON missing '{required}'")
    return data


def build_assertion(service_account: dict, subject: str, issued_at: int) -> str:
    """Build a signed RS256 JWT assertion impersonating ``subject``.

    ``issued_at`` is an epoch second (passed in rather than read from the clock so the claims are
    deterministic and testable).
    """
    claims = {
        "iss": service_account["client_email"],
        "sub": subject,
        "scope": CALENDAR_SCOPE,
        "aud": service_account.get("token_uri", DEFAULT_TOKEN_URI),
        "iat": issued_at,
        "exp": issued_at + _ASSERTION_TTL_SECONDS,
    }
    return jwt.encode(claims, service_account["private_key"], algorithm="RS256")


class GoogleAuth:
    """Mints and caches access tokens for impersonated Workspace calendar access."""

    def __init__(self, service_account_json: str | None) -> None:
        self._service_account = parse_service_account(service_account_json)

    def _token_uri(self) -> str:
        return str(self._service_account.get("token_uri", DEFAULT_TOKEN_URI))

    def get_access_token(self, subject: str) -> str:
        """Return a valid access token for impersonating ``subject``, minting one if needed."""
        if not subject:
            raise GoogleAuthError("cannot mint a token without a subject (provider calendar email)")

        cache = get_cache()
        cache_key = f"gcal:token:{subject}"
        cached = cache.get(cache_key)
        if cached:
            return str(cached)

        token, ttl = self._exchange(subject)
        cache.set(cache_key, token, timeout_seconds=max(ttl - _TOKEN_CACHE_SAFETY_MARGIN_SECONDS, 60))
        return token

    def _exchange(self, subject: str) -> tuple[str, int]:
        """Perform the JWT-bearer token exchange. Returns ``(access_token, expires_in)``."""
        assertion = build_assertion(self._service_account, subject, arrow.utcnow().int_timestamp)

        http = Http()
        response = http.post(
            self._token_uri(),
            data={"grant_type": JWT_BEARER_GRANT, "assertion": assertion},
        )
        if response.status_code != 200:
            # Surface Google's error body (it does not contain PHI) to make misconfiguration of the
            # service account or domain-wide delegation diagnosable.
            log.error(
                "Google token exchange failed for %s: %s %s",
                subject,
                response.status_code,
                response.text,
            )
            raise GoogleAuthError(
                f"token exchange returned {response.status_code} for subject {subject}"
            )

        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise GoogleAuthError(f"token exchange response had no access_token for {subject}")
        return access_token, int(payload.get("expires_in", _ASSERTION_TTL_SECONDS))
