"""Configuration, input validation, origin checks and rate limiting for the public endpoints.

Everything here is a plain function so it can be unit tested without a handler.
Every check fails closed: a missing or malformed setting denies the request.
"""

import datetime
import re
from typing import Any

# --- Configuration ---------------------------------------------------------------

ENABLED_SECRET = "PUBLIC_BOOKING_ENABLED"
NOTE_TYPE_SECRET = "PUBLIC_BOOKING_NOTE_TYPE_NAME"
LEAD_TIME_SECRET = "PUBLIC_BOOKING_LEAD_TIME_MINUTES"
WINDOW_DAYS_SECRET = "PUBLIC_BOOKING_WINDOW_DAYS"
TEAM_SECRET = "PUBLIC_BOOKING_TASK_TEAM_ID"
ALLOWED_HOSTS_SECRET = "PUBLIC_BOOKING_ALLOWED_HOSTS"

DEFAULT_LEAD_TIME_MINUTES = 120
MAX_LEAD_TIME_MINUTES = 60 * 24 * 14
DEFAULT_WINDOW_DAYS = 14
MAX_WINDOW_DAYS = 14  # slot holds live in the cache, whose TTL ceiling is 14 days


def is_enabled(secrets: Any) -> bool:
    """True only when PUBLIC_BOOKING_ENABLED is exactly "true" (case-insensitive).

    Unset, blank or any other value means off. The plugin ships off.
    """
    return str(secrets.get(ENABLED_SECRET) or "").strip().lower() == "true"


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if n < low or n > high:
        return default
    return n


def lead_time_minutes(secrets: Any) -> int:
    """Minutes from now before the first bookable slot (default 120)."""
    return _bounded_int(
        secrets.get(LEAD_TIME_SECRET),
        DEFAULT_LEAD_TIME_MINUTES,
        0,
        MAX_LEAD_TIME_MINUTES,
    )


def window_days(secrets: Any) -> int:
    """How many days ahead slots are offered (default 14, max 14)."""
    return _bounded_int(
        secrets.get(WINDOW_DAYS_SECRET), DEFAULT_WINDOW_DAYS, 1, MAX_WINDOW_DAYS
    )


# --- Input validation --------------------------------------------------------------

MAX_BODY_BYTES = 8 * 1024
NAME_MAX = 60
EMAIL_MAX = 254
REASON_MAX = 300
ID_MAX = 64

# Letters (any script), spaces, apostrophes, hyphens and periods. No digits, no markup.
NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ '.\-][^\W\d_]+)*\.?$")
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,}$"
)
PHONE_DIGITS_PATTERN = re.compile(r"^1?(\d{10})$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9\-]{1,64}$")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ValidationError(ValueError):
    """Raised with a field name when a booking payload fails validation."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


def _required_str(payload: Any, field: str, max_len: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValidationError(field, "is required")
    value = value.strip()
    if not value:
        raise ValidationError(field, "is required")
    if len(value) > max_len:
        raise ValidationError(field, f"must be at most {max_len} characters")
    if CONTROL_CHARS.search(value):
        raise ValidationError(field, "contains invalid characters")
    return value


def normalize_phone(raw: str) -> str | None:
    """Returns the 10-digit US phone number, or None if `raw` isn't one."""
    digits = re.sub(r"[\s().+\-]", "", raw)
    match = PHONE_DIGITS_PATTERN.match(digits)
    return match.group(1) if match else None


def validate_booking(payload: Any, *, today: datetime.date) -> dict[str, Any]:
    """Validates and normalizes a public booking payload.

    Returns a dict with keys first_name, last_name, birth_date (date), email
    (lowercased), phone (10 digits), provider_id, start_time (aware datetime) and
    reason (str, may be empty). Raises ValidationError on the first bad field.
    """
    if not isinstance(payload, dict):
        raise ValidationError("body", "must be a JSON object")

    first_name = _required_str(payload, "first_name", NAME_MAX)
    last_name = _required_str(payload, "last_name", NAME_MAX)
    for field, value in (("first_name", first_name), ("last_name", last_name)):
        if not NAME_PATTERN.match(value):
            raise ValidationError(field, "must contain letters only")

    dob_raw = _required_str(payload, "birth_date", 10)
    try:
        birth_date = datetime.date.fromisoformat(dob_raw)
    except ValueError as exc:
        raise ValidationError("birth_date", "must be YYYY-MM-DD") from exc
    if birth_date > today or birth_date.year < today.year - 120:
        raise ValidationError("birth_date", "is out of range")

    email = _required_str(payload, "email", EMAIL_MAX).lower()
    if not EMAIL_PATTERN.match(email):
        raise ValidationError("email", "is not a valid email address")

    phone = normalize_phone(_required_str(payload, "phone", 20))
    if phone is None:
        raise ValidationError("phone", "must be a 10-digit US phone number")

    provider_id = _required_str(payload, "provider_id", ID_MAX)
    if not ID_PATTERN.match(provider_id):
        raise ValidationError("provider_id", "is invalid")

    start_raw = _required_str(payload, "start_iso", 40)
    try:
        start_time = datetime.datetime.fromisoformat(start_raw)
    except ValueError as exc:
        raise ValidationError("start_iso", "must be an ISO 8601 datetime") from exc
    if start_time.tzinfo is None:
        raise ValidationError("start_iso", "must include a UTC offset")

    reason_raw = payload.get("reason", "")
    if reason_raw is None:
        reason_raw = ""
    if not isinstance(reason_raw, str):
        raise ValidationError("reason", "must be text")
    reason = reason_raw.strip()
    if len(reason) > REASON_MAX:
        raise ValidationError("reason", f"must be at most {REASON_MAX} characters")
    if CONTROL_CHARS.search(reason):
        raise ValidationError("reason", "contains invalid characters")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "birth_date": birth_date,
        "email": email,
        "phone": phone,
        "provider_id": provider_id,
        "start_time": start_time,
        "reason": reason,
    }


# --- Origin (CSRF) check -------------------------------------------------------------


def hostname_from_url(url: str) -> str:
    """Hostname of `url`, lowercased, without port or userinfo.

    Plain string handling because `urllib.parse.urlparse` is not on the plugin
    sandbox allowlist.
    """
    rest = url.split("://", 1)[-1]
    rest = rest.split("/", 1)[0]
    rest = rest.rsplit("@", 1)[-1]
    if rest.startswith("["):
        return rest.split("]", 1)[0].lstrip("[").lower()
    return rest.split(":", 1)[0].lower()


def allowed_hosts(
    secrets: Any,
    environment: Any,
    headers: Any,
) -> set[str]:
    """Hosts a browser request may come from: the instance itself plus any configured extras."""
    hosts: set[str] = set()
    customer = str(environment.get("CUSTOMER_IDENTIFIER") or "").strip().lower()
    if customer:
        hosts.add(f"{customer}.canvasmedical.com")
    forwarded = str(headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    if forwarded:
        hosts.add(hostname_from_url(forwarded))
    for extra in str(secrets.get(ALLOWED_HOSTS_SECRET) or "").split(","):
        extra = extra.strip().lower()
        if extra:
            hosts.add(hostname_from_url(extra))
    return hosts


def origin_allowed(headers: Any, hosts: set[str]) -> bool:
    """CSRF guard for the booking POST.

    A request whose Origin (or, failing that, Referer) names a host outside
    `hosts` is rejected. A request with neither header is a non-browser client:
    CSRF does not apply to it (there is no ambient session to ride on, and the
    JSON content-type check already forces a CORS preflight in browsers), so it
    is allowed and left to the rate limit. If an Origin is present but no
    allowed host can be determined, the request is rejected (fail closed).
    """
    header = str(headers.get("Origin") or headers.get("Referer") or "").strip()
    if not header:
        return True
    if header == "null":
        return False
    host = hostname_from_url(header)
    return bool(host) and host in hosts


def is_json_request(headers: Any) -> bool:
    """True when Content-Type is application/json.

    Browsers cannot send this cross-site without a CORS preflight, which the
    plugin never approves, so requiring it blocks simple-form CSRF posts.
    """
    content_type = (
        str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    )
    return content_type == "application/json"


# --- Rate limiting ---------------------------------------------------------------------

SLOTS_LIMIT = (60, 600)  # 60 slot lookups per client per 10 minutes
BOOK_LIMIT_PER_CLIENT = (5, 3600)  # 5 booking attempts per client per hour
BOOK_LIMIT_PER_EMAIL = (3, 86400)  # 3 booking attempts per email per day
BOOK_LIMIT_GLOBAL = (200, 3600)  # 200 booking attempts per instance per hour


IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$"
)
IPV6_PATTERN = re.compile(r"^[0-9A-Fa-f:]{2,39}$")
SHARED_CLIENT_KEY = "unknown"


def client_key(headers: Any) -> str:
    """Best-effort client identifier for rate limiting. NOT a trusted identity.

    Measured on a Canvas instance (2026-11-03): the platform hands the plugin a
    single X-Forwarded-For value. With no caller header it is the real client IP;
    when the caller sends its own X-Forwarded-For, the caller's FIRST value is
    passed through and the real IP is dropped. X-Real-Ip and Forwarded are passed
    through from the caller unchanged. So no header the plugin sees is trusted,
    and per-client limits can be dodged by a caller who sets X-Forwarded-For.
    The per-email and instance-wide limits are the real backstop.

    What this function does: takes the last X-Forwarded-For hop (the hop a proxy
    appends, if a deployment ever appends one) and accepts it only if it is an IP
    literal. Anything else, including caller-chosen X-Real-Ip, goes into one
    shared bucket, so junk strings can't mint fresh buckets.
    """
    forwarded = str(headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
    if IPV4_PATTERN.match(forwarded) or (
        ":" in forwarded and IPV6_PATTERN.match(forwarded)
    ):
        return forwarded.lower()
    return SHARED_CLIENT_KEY


def hit_rate_limit(cache: Any, key: str, limit: tuple[int, int]) -> bool:
    """Counts one hit against `key`; True if the caller is over `limit`.

    Fixed-window counter on the plugin cache. The cache has no atomic increment,
    so two requests racing on the same key can each read the old count; the limit
    is a burst guard, not an exact quota. Cache errors propagate (the request
    fails with a 500) rather than letting traffic through unlimited.
    """
    max_hits, window_seconds = limit
    cache_key = f"rl:{key}"
    count = int(cache.get(cache_key) or 0)
    if count >= max_hits:
        return True
    cache.set(cache_key, count + 1, timeout_seconds=window_seconds)
    return False
