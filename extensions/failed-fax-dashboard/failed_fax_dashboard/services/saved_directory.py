"""Who owns a fax number in the Saved Directory, the contact list the fax pop-up searches.

The Saved Directory lives in Canvas's central contact service, not in the instance
database, so a contact picked there leaves nothing on the instance but the number.
The SDK's ``science_http`` client reaches that service read-only.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.utils.http import science_http
from logger import log
from requests import RequestException

from failed_fax_dashboard.services.util import last_ten

SAVED_DIRECTORY_SOURCE = "Matched in the Saved Directory"
CONTACTS_PATH = "/contacts/"
CACHE_SECONDS = 24 * 60 * 60
# A first load after install can meet many numbers; the rest fill in on later loads.
MAX_LOOKUPS_PER_LOAD = 25
PAGE_SIZE = 10
NO_MATCH: dict[str, str] = {}


@dataclass(frozen=True)
class SavedContact:
    """A Saved Directory contact, shaped like the instance's ServiceProvider."""

    first_name: str
    last_name: str
    practice_name: str
    specialty: str
    business_phone: str
    business_fax: str
    business_address: str


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _from_row(row: dict[str, Any]) -> dict[str, str]:
    """The fields the contact card uses, as plain strings that cache cleanly."""
    return {
        "first_name": _text(row.get("firstName")),
        "last_name": _text(row.get("lastName")),
        "practice_name": _text(row.get("practiceName")),
        "specialty": _text(row.get("specialty")),
        "business_phone": _text(row.get("businessPhone")),
        "business_fax": _text(row.get("businessFax")),
        "business_address": _text(row.get("businessAddress")),
    }


def _fetch(digits: str) -> dict[str, str] | None:
    """The one contact with this fax number, ``NO_MATCH``, or None when the service failed.

    Results are re-checked on the last 10 digits, so a loose match on the service's side
    can't name the wrong contact. Two or more contacts with the number is no match.
    """
    query = urlencode({"business_fax": digits, "format": "json", "limit": PAGE_SIZE})
    try:
        response = science_http.get_json(f"{CONTACTS_PATH}?{query}")
    except RequestException as exc:
        log.warning(f"Saved Directory lookup failed: {exc!r}")
        return None
    body = response.json()
    if response.status_code != 200 or not isinstance(body, dict):
        log.warning(f"Saved Directory lookup returned status {response.status_code}")
        return None
    rows = body.get("results")
    if not isinstance(rows, list):
        return None
    matches = [
        row for row in rows if isinstance(row, dict) and last_ten(_text(row.get("businessFax"))) == digits
    ]
    return _from_row(matches[0]) if len(matches) == 1 else NO_MATCH


def saved_matches(numbers: list[str]) -> dict[str, SavedContact]:
    """Saved Directory contacts by last 10 digits of fax number, only where exactly one matches.

    Answers are cached for a day, including "no match". A failed lookup isn't cached, so
    it's tried again on the next load. At most ``MAX_LOOKUPS_PER_LOAD`` numbers are looked
    up per call.
    """
    wanted = sorted({last_ten(number) for number in numbers if len(last_ten(number)) == 10})
    if not wanted:
        return {}
    cache = get_cache()
    keys = {digits: f"saved-directory:{digits}" for digits in wanted}
    # get_many answers under the plugin-prefixed key, so map back on the key's end.
    cached = {
        key: value
        for full_key, value in cache.get_many(keys.values()).items()
        for key in keys.values()
        if full_key == key or full_key.endswith(f":{key}")
    }
    found: dict[str, SavedContact] = {}
    lookups = 0
    for digits in wanted:
        fields = cached.get(keys[digits])
        if fields is None:
            if lookups >= MAX_LOOKUPS_PER_LOAD:
                continue
            lookups += 1
            fields = _fetch(digits)
            if fields is None:
                continue
            cache.set(keys[digits], fields, timeout_seconds=CACHE_SECONDS)
        if fields:
            found[digits] = SavedContact(**fields)
    return found
