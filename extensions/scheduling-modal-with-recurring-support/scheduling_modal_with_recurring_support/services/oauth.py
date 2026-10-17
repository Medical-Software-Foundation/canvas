from typing import Any, NamedTuple

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils import Http


# Canvas client_credentials tokens typically last 60 min. Cache for 50 min
# unless the response carries a shorter expires_in, in which case we shave
# 60 s off and respect that.
DEFAULT_TTL_SECONDS = 50 * 60
EXPIRY_SAFETY_MARGIN_SECONDS = 60


class OAuthToken(NamedTuple):
    access_token: str
    token_type: str


def _cache_key(instance_url: str, client_id: str) -> str:
    return f"oauth_token::{instance_url.rstrip('/')}::{client_id}"


def acquire_token(
    instance_url: str,
    client_id: str,
    client_secret: str,
) -> OAuthToken:
    """Acquire a client-credentials OAuth token, cached in plugin Redis.

    Without caching, every plugin endpoint posts to /auth/token/ on the same
    home-app-web container, doubling the DB connection cost per request and
    deadlocking the SQLAlchemy pool under modest fan-out.
    """
    cache = get_cache()
    key = _cache_key(instance_url, client_id)

    cached = cache.get(key)
    if cached:
        return OAuthToken(
            access_token=cached["access_token"],
            token_type=cached.get("token_type", "Bearer"),
        )

    token_url = f"{instance_url.rstrip('/')}/auth/token/"
    http = Http()
    response = http.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if not response.ok:
        raise RuntimeError(
            f"OAuth token request failed: {response.status_code} {response.text}"
        )

    payload: dict[str, Any] = response.json()
    token = OAuthToken(
        access_token=payload["access_token"],
        token_type=payload.get("token_type", "Bearer"),
    )

    expires_in = payload.get("expires_in")
    try:
        ttl = int(expires_in) - EXPIRY_SAFETY_MARGIN_SECONDS if expires_in else DEFAULT_TTL_SECONDS
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_SECONDS
    if ttl < 60:
        ttl = 60

    cache.set(
        key,
        {"access_token": token.access_token, "token_type": token.token_type},
        ttl,
    )
    return token
