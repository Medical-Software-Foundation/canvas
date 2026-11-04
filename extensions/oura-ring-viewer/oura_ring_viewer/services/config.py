"""Request and configuration helpers shared by both protocols.

URL handling is done by hand: the Canvas plugin sandbox allows only
``urlencode`` and ``quote`` from ``urllib.parse``.
"""

from typing import Any
from urllib.parse import quote

from oura_ring_viewer.services.oura_client import OuraClient
from oura_ring_viewer.services.settings import (
    MAX_PATIENT_ID_LENGTH,
    MIN_SECRET_LENGTH,
    PLUGIN_API_PATH,
)

CLIENT_ID = "OURA_CLIENT_ID"
CLIENT_SECRET = "OURA_CLIENT_SECRET"
REDIRECT_URI = "OURA_REDIRECT_URI"
ENVIRONMENT = "OURA_ENVIRONMENT"
MAGIC_LINK_SECRET = "OURA_MAGIC_LINK_SECRET"

# What each operation actually needs, so a missing value is reported only where
# it matters. Fetching never signs anything; sending a link never calls Oura.
FETCH_SECRETS: tuple[str, ...] = (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, ENVIRONMENT)
LINK_SECRETS: tuple[str, ...] = (MAGIC_LINK_SECRET, REDIRECT_URI)
OAUTH_SECRETS: tuple[str, ...] = (*FETCH_SECRETS, MAGIC_LINK_SECRET)

_LOCAL_HOSTS = ("localhost", "127.0.0.1")


def clean_patient_id(raw: Any) -> str | None:
    """Return the patient id if it is a plausible Canvas key, else None.

    Canvas ids are short alphanumeric strings. Accepting only letters, digits
    and hyphens means an id can never carry markup or script into a template,
    whatever the template engine's escaping does.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or len(value) > MAX_PATIENT_ID_LENGTH:
        return None
    if not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in value):
        return None
    return value


def config_problems(secrets: dict[str, str] | None, required: tuple[str, ...]) -> list[str]:
    """Names of required settings that are missing or unusable."""
    values = secrets or {}
    problems = [name for name in required if not values.get(name)]
    secret = values.get(MAGIC_LINK_SECRET) if MAGIC_LINK_SECRET in required else None
    if secret and len(secret) < MIN_SECRET_LENGTH:
        problems.append(f"{MAGIC_LINK_SECRET} (shorter than {MIN_SECRET_LENGTH} characters)")
    redirect = values.get(REDIRECT_URI) if REDIRECT_URI in required else None
    if redirect and _origin(redirect) is None:
        problems.append(f"{REDIRECT_URI} (must be an absolute https URL)")
    return problems


def build_client(secrets: dict[str, str]) -> OuraClient:
    """Construct an Oura client from validated plugin settings."""
    return OuraClient(
        environment=secrets[ENVIRONMENT],
        client_id=secrets[CLIENT_ID],
        client_secret=secrets[CLIENT_SECRET],
        redirect_uri=secrets[REDIRECT_URI],
    )


def connect_url(redirect_uri: str, token: str) -> str:
    """The patient-facing ``/connect`` URL, on the same host as the callback."""
    origin = _origin(redirect_uri)
    if origin is None:
        raise ValueError("redirect URI must be an absolute https URL")
    return f"{origin}{PLUGIN_API_PATH}/connect?token={quote(token, safe='')}"


def _origin(url: str) -> str | None:
    """``scheme://host[:port]`` for an https URL (or http on localhost)."""
    scheme, sep, rest = (url or "").strip().partition("://")
    host = rest.partition("/")[0].partition("?")[0]
    scheme = scheme.lower()
    if sep != "://" or not host or "@" in host:
        return None
    hostname = host.rsplit(":", 1)[0].lower() if not host.startswith("[") else host
    if scheme == "https" or (scheme == "http" and hostname in _LOCAL_HOSTS):
        return f"{scheme}://{host}"
    return None
