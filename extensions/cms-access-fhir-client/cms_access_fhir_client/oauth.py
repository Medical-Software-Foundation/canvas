"""OAuth 2.0 client-credentials flow with token caching.

The CMS ACCESS Operations Manual v0.9.11 (§Authentication) documents the token
request as form-encoded credentials: ``grant_type``, ``client_id``,
``client_secret`` and ``scope`` in an ``application/x-www-form-urlencoded`` body.
However, a previous testing cycle found the CMS authorization server accepting
only HTTP Basic auth (credentials in the ``Authorization`` header, body limited to
``grant_type``/``scope``) and rejecting form-field credentials with 401.

The CMS IMPL token endpoint is CMS IDM (Okta), which uses HTTP Basic
(``client_secret_basic``) — confirmed live: a Basic token request returns 200 while
form-field credentials are rejected. So ``auto`` tries Basic first and falls back to
form-field on a 401 (covering any non-Okta ACCESS server), logging which style
succeeded. ``ACCESS_OAUTH_AUTH_STYLE`` (``post`` | ``basic`` | ``auto``, default
``auto``) can pin a single style.
"""
import base64

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils import Http
from logger import log

_FORM_URLENCODED = "application/x-www-form-urlencoded"


def _request_token_post(http: Http, token_url: str, client_id: str, client_secret: str, scope: str):
    """Token request with credentials as form fields (Operations Manual v0.9.11 style)."""
    return http.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
        headers={"Content-Type": _FORM_URLENCODED},
    )


def _request_token_basic(http: Http, token_url: str, client_id: str, client_secret: str, scope: str):
    """Token request with HTTP Basic auth (credentials in the Authorization header)."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return http.post(
        token_url,
        data={"grant_type": "client_credentials", "scope": scope},
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": _FORM_URLENCODED,
        },
    )


def get_access_token(secrets: dict) -> str:
    """Return a valid CMS ACCESS OAuth access token, fetching a new one if needed.

    Token is cached with TTL = (expires_in - 120s) to guard against clock skew and the
    short (~5 min) CMS token lifetime. Fails closed: raises ValueError if any required
    secret is absent.
    """
    client_id = secrets.get("ACCESS_OAUTH_CLIENT_ID")
    client_secret = secrets.get("ACCESS_OAUTH_CLIENT_SECRET")
    token_url = secrets.get("ACCESS_OAUTH_TOKEN_URL")
    # Scope is provided during client registration; fall back to the scopes CMS has
    # echoed in practice if it is not configured.
    scope = secrets.get("ACCESS_OAUTH_SCOPE", "cdx/*.read cdx/fhir-resource.write")
    auth_style = (secrets.get("ACCESS_OAUTH_AUTH_STYLE") or "auto").strip().lower()

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

    # Order the attempts: honor a pinned style, otherwise try Basic first (confirmed
    # correct for CMS IDM/Okta) and fall back to form-field on 401.
    if auth_style == "basic":
        attempts = [("basic", _request_token_basic)]
    elif auth_style == "post":
        attempts = [("post", _request_token_post)]
    else:
        attempts = [("basic", _request_token_basic), ("post", _request_token_post)]

    response = None
    for style, request in attempts:
        response = request(http, token_url, client_id, client_secret, scope)
        if response.ok:
            log.info(f"[cms-access] OAuth token obtained via '{style}' auth style")
            break
        if response.status_code != 401 or style == attempts[-1][0]:
            # Non-401 errors are not auth-style problems; the last attempt is terminal.
            break
        log.warning(
            f"[cms-access] OAuth '{style}' auth style returned 401; trying next style"
        )

    if response is None or not response.ok:
        status = response.status_code if response is not None else "no response"
        body = response.text if response is not None else ""
        raise RuntimeError(f"OAuth token request failed: {status} {body}")

    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError("OAuth response missing access_token field")

    expires_in = token_data.get("expires_in", 300)
    # Buffer of 120s (per the manual's "refresh 2 minutes before expiration" guidance)
    # so we never use a token in its last two minutes of life.
    ttl = max(int(expires_in) - 120, 30)

    cache.set(cache_key, access_token, timeout_seconds=ttl)
    log.info(f"[cms-access] OAuth token refreshed, TTL={ttl}s")

    return access_token
