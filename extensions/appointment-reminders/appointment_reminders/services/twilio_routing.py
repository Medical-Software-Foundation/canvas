"""Is Twilio actually routing inbound SMS to this plugin?

Credentials being present says nothing about routing. A number whose "A message
comes in" webhook is cleared, or pointed elsewhere, accepts outbound sends
perfectly while every patient reply is silently discarded — no error, no log, no
audit row, because the request never reaches the plugin at all. That happened on
a live instance and went unnoticed for five days.

So the admin app asks Twilio directly rather than inferring routing from the
presence of an auth token.

Deliberately biased toward *not* crying wolf: ``NOT_ROUTED`` is returned only
when neither the number nor any Messaging Service points here. Anything the API
cannot settle — unreachable, unauthorized, number not in this account, a TwiML
app governing the number — comes back ``UNKNOWN`` so the UI can say "couldn't
check" instead of alarming an install that is fine.
"""
from __future__ import annotations

from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils.http import Http
from logger import log

from appointment_reminders.services.delivery import _normalize_phone, _twilio_auth

ROUTED = "routed"
NOT_ROUTED = "not_routed"
UNKNOWN = "unknown"

_API_BASE = "https://api.twilio.com"
_MESSAGING_BASE = "https://messaging.twilio.com"

# The admin page hits this on every load and the SDK's HTTP client enforces a
# fixed 30s timeout with no per-request override, so the result is cached. Short
# enough that re-pointing a webhook shows up while someone is still looking at
# the page.
_CACHE_TTL_SECONDS = 300


def _expected_url(secrets: dict[str, str]) -> str:
    return (secrets.get("twilio-inbound-webhook-url") or "").strip()


def _cache_key(secrets: dict[str, str]) -> str:
    """Keyed on the inputs, so changing either re-checks instead of serving stale."""
    number = (secrets.get("twilio-phone-number") or "").strip()
    return f"cr:inbound_route:{hash((_expected_url(secrets), number))}"


def inbound_webhook_status(secrets: dict[str, str]) -> str:
    """Return ROUTED / NOT_ROUTED / UNKNOWN for the plugin's inbound webhook."""
    expected = _expected_url(secrets)
    if not expected:
        # Nothing to route to. Two-way confirm cannot work, and the signature
        # check fails closed on every request, so this is a definite negative.
        return NOT_ROUTED

    cache = get_cache()
    key = _cache_key(secrets)
    cached = cache.get(key)
    if cached in (ROUTED, NOT_ROUTED, UNKNOWN):
        return cached

    status = _check_routing(secrets, expected)
    cache.set(key, status, timeout_seconds=_CACHE_TTL_SECONDS)
    return status


def _check_routing(secrets: dict[str, str], expected: str) -> str:
    """Ask Twilio where the configured number's inbound messages go."""
    account_sid = (secrets.get("twilio-account-sid") or "").strip()
    number = _normalize_phone((secrets.get("twilio-phone-number") or "").strip())
    if not account_sid or not number:
        return UNKNOWN

    auth = _twilio_auth(secrets)

    number_status = _number_routing(account_sid, number, auth, expected)
    if number_status in (ROUTED, UNKNOWN):
        return number_status

    # The number itself does not point here. It may still be governed by a
    # Messaging Service whose inbound_request_url does — the arrangement the
    # README recommends for two-way confirm — so check those before reporting a
    # problem.
    return _messaging_service_routing(auth, expected)


def _number_routing(
    account_sid: str, number: str, auth: tuple[str, str], expected: str
) -> str:
    """Compare the number's own ``sms_url`` against the expected webhook."""
    try:
        response = Http(base_url=_API_BASE).get(
            f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json"
            f"?PhoneNumber={number}",
            headers=_basic_auth_header(auth),
        )
    except Exception as exc:  # network/DNS/timeout — cannot conclude anything
        log.warning(f"[routing] Could not read Twilio numbers: {exc}")
        return UNKNOWN

    if response.status_code != 200:
        log.warning(
            f"[routing] Twilio numbers lookup returned {response.status_code}; "
            "cannot verify inbound routing"
        )
        return UNKNOWN

    numbers = (response.json() or {}).get("incoming_phone_numbers") or []
    match = next(
        (n for n in numbers if _normalize_phone(n.get("phone_number", "")) == number),
        None,
    )
    if match is None:
        # Hosted numbers and short codes do not appear here, so absence is not
        # evidence of misrouting.
        return UNKNOWN
    if match.get("sms_application_sid"):
        # Twilio ignores every sms_*_url when a TwiML app is set, so the number's
        # own sms_url tells us nothing.
        return UNKNOWN
    return ROUTED if (match.get("sms_url") or "").strip() == expected else NOT_ROUTED


def _messaging_service_routing(auth: tuple[str, str], expected: str) -> str:
    """True if any Messaging Service posts inbound messages to the expected URL."""
    try:
        response = Http(base_url=_MESSAGING_BASE).get(
            "/v1/Services?PageSize=100", headers=_basic_auth_header(auth)
        )
    except Exception as exc:
        log.warning(f"[routing] Could not read Twilio messaging services: {exc}")
        return UNKNOWN

    if response.status_code != 200:
        log.warning(
            f"[routing] Messaging services lookup returned {response.status_code}; "
            "cannot verify inbound routing"
        )
        return UNKNOWN

    services = (response.json() or {}).get("services") or []
    for service in services:
        if (service.get("inbound_request_url") or "").strip() != expected:
            continue
        # A service pointing here only governs numbers that have not been told to
        # use their own webhook instead.
        if service.get("use_inbound_webhook_on_number"):
            continue
        return ROUTED
    return NOT_ROUTED


def _basic_auth_header(auth: tuple[str, str]) -> dict[str, str]:
    import base64

    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def describe(status: str) -> dict[str, Any]:
    """Presentation contract for the admin page's integration panel."""
    return {
        ROUTED: {"ok": True, "label": "Configured"},
        NOT_ROUTED: {
            "ok": False,
            "label": "Outbound only — patient replies are being dropped",
        },
        UNKNOWN: {"ok": True, "label": "Configured (inbound routing unverified)"},
    }.get(status, {"ok": True, "label": "Configured (inbound routing unverified)"})
