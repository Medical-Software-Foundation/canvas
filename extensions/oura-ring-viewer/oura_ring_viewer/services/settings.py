"""Plugin-wide constants and Oura environment routing.

The URLs, scope strings, endpoint paths and query parameters below were
verified on 2026-11-02 against Oura's published OpenAPI specification (1.43)
and against live sandbox responses. If Oura changes them, correct them here
rather than at the call sites.

This module has no ``canvas_sdk`` or Django dependency on purpose, so the
pure normalization layer and its tests can import from it freely.
"""

PLUGIN_NAME: str = "oura_ring_viewer"
PLUGIN_API_PATH: str = f"/plugin-io/api/{PLUGIN_NAME}"

DEFAULT_RANGE_DAYS: int = 14
RANGE_OPTIONS: tuple[int, ...] = (7, 14, 30, 90)

# A staff-sent connection link lasts three days. It is often delivered through
# the patient portal and read later, so a short window mostly produced dead
# links. It stays single use and bound to one patient. The OAuth ``state``
# only has to survive Oura's sign-in and consent screens, so an hour is enough.
MAGIC_LINK_TTL_SECONDS: int = 72 * 60 * 60
STATE_TTL_SECONDS: int = 60 * 60

# HMAC-SHA256 keys shorter than the hash output weaken the signature, and
# PyJWT warns on them. Refuse to sign or verify with a short secret.
MIN_SECRET_LENGTH: int = 32

# Canvas patient ids are short alphanumeric keys. Anything else is rejected at
# every route before it reaches the database or a template.
MAX_PATIENT_ID_LENGTH: int = 64

DISCLAIMER: str = (
    "Oura Ring data is consumer wellness data shared by the patient. It is not "
    "a medical device measurement and is not a substitute for clinical vitals."
)

# Guard against a misbehaving ``next_token`` looping forever. A 90 day window
# of daily summaries fits in a single page, so 20 is generous.
MAX_PAGES: int = 20

# Oura hosted authorization lives on cloud.ouraring.com; the token exchange and
# all data reads live on api.ouraring.com.
OURA_AUTHORIZE_URL: str = "https://cloud.ouraring.com/oauth/authorize"
OURA_API_HOST: str = "https://api.ouraring.com"
OURA_TOKEN_PATH: str = "/oauth/token"

# Request only the scopes v1 actually reads. ``daily`` covers the sleep,
# readiness and activity summaries plus sleep periods; ``spo2`` covers the
# overnight oxygen summary. ``personal`` (age, weight, sex, email), intraday
# ``heartrate`` and ``workout`` are deliberately NOT requested: v1 never reads
# them, and not holding them is a stronger security-review and data
# minimization position than holding and ignoring them.
OURA_OAUTH_SCOPE: str = "daily spo2"

# Collection endpoints, joined onto the environment collection path.
ENDPOINT_DAILY_SLEEP: str = "daily_sleep"
ENDPOINT_SLEEP_PERIODS: str = "sleep"
ENDPOINT_DAILY_READINESS: str = "daily_readiness"
ENDPOINT_DAILY_ACTIVITY: str = "daily_activity"
ENDPOINT_DAILY_SPO2: str = "daily_spo2"

# Metric families: one normalized summary per day per family.
# Sleep is built from two endpoints (the daily score plus the main sleep
# period's raw measurements); the others map one endpoint to one family.
FAMILY_SLEEP: str = "sleep"
FAMILY_READINESS: str = "readiness"
FAMILY_ACTIVITY: str = "activity"
FAMILY_SPO2: str = "spo2"
FAMILIES: tuple[str, ...] = (FAMILY_SLEEP, FAMILY_READINESS, FAMILY_ACTIVITY, FAMILY_SPO2)

def oura_collection_path(environment: str) -> str:
    """Return the usercollection path for the given environment string.

    Oura's sandbox is a path prefix on the same host, not a separate host, and
    it serves the same response shapes as production. That is what lets this
    plugin be built and reviewed without a physical ring. Anything other than
    the exact string ``production`` routes to the sandbox, so a typo in the
    environment variable cannot reach live patient data.
    """
    env = (environment or "").strip().lower()
    if env == "production":
        return "/v2/usercollection"
    return "/v2/sandbox/usercollection"


def oura_collection_base(environment: str) -> str:
    """Return the full usercollection base URL for the given environment."""
    return f"{OURA_API_HOST}{oura_collection_path(environment)}"


def parse_range_days(raw: str | None) -> int:
    """Coerce a range query parameter into an allowed day count."""
    if not raw:
        return DEFAULT_RANGE_DAYS
    cleaned = raw.strip().lower().rstrip("d")
    try:
        days = int(cleaned)
    except (TypeError, ValueError):
        return DEFAULT_RANGE_DAYS
    if days not in RANGE_OPTIONS:
        return DEFAULT_RANGE_DAYS
    return days
