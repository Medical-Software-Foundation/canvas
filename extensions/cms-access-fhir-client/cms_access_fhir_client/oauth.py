"""OAuth 2.0 client-credentials flow with token caching."""
from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils import Http
from logger import log


def get_access_token(secrets: dict) -> str:
    """Return a valid CMS ACCESS OAuth access token, fetching a new one if needed.

    Token is cached with TTL = (expires_in - 60s) to guard against edge-case expiry.
    Fails closed: raises ValueError if any required secret is absent.
    """
    client_id = secrets.get("ACCESS_OAUTH_CLIENT_ID")
    client_secret = secrets.get("ACCESS_OAUTH_CLIENT_SECRET")
    token_url = secrets.get("ACCESS_OAUTH_TOKEN_URL")

    if not client_id:
        raise ValueError("Missing required secret: ACCESS_OAUTH_CLIENT_ID")
    if not client_secret:
        raise ValueError("Missing required secret: ACCESS_OAUTH_CLIENT_SECRET")
    if not token_url:
        raise ValueError("Missing required secret: ACCESS_OAUTH_TOKEN_URL")

    cache = get_cache()
    cache_key = f"access_oauth_token_{client_id}"

    cached = cache.get(cache_key)
    if cached:
        return cached

    http = Http()
    response = http.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )

    if not response.ok:
        raise RuntimeError(
            f"OAuth token request failed: {response.status_code} {response.text}"
        )

    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError("OAuth response missing access_token field")

    expires_in = token_data.get("expires_in", 3600)
    # Buffer of 60s so we never use a token in its last minute of life
    ttl = max(int(expires_in) - 60, 60)

    cache.set(cache_key, access_token, timeout_seconds=ttl)
    log.info(f"[cms-access] OAuth token refreshed, TTL={ttl}s")

    return access_token
