"""Chart app that opens the patient's Tellescope profile in the right chart pane.

How the profile link is found:

- With TELLESCOPE_API_KEY set, the app asks the Tellescope API for the enduser
  linked to this Canvas patient (``source`` "Canvas" with ``externalId`` equal to
  the patient key, or a "Canvas" entry in ``references``) and opens that
  enduser's profile.
- Without an API key, it uses the same TELLESCOPE_PROFILE_URL_TEMPLATE link as
  the banner.

Every failure shows a short fixed message in the pane. Exception text and
response bodies are never shown or logged; logs carry ids, status codes and
exception class names only.
"""

import json
from typing import Any
from urllib.parse import quote, urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.utils.http import Http
from logger import log
from requests import RequestException

from tellescope_banner.handlers.banner import template_profile_url

TITLE = "Tellescope Profile"

API_KEY_SETTING = "TELLESCOPE_API_KEY"
API_URL_SETTING = "TELLESCOPE_API_URL"
DEFAULT_API_URL = "https://api.tellescope.com/v1"
PROFILE_BASE_URL = "https://business.tellescope.com/endusers/"

MSG_NO_PATIENT = "No patient is open. Open a patient chart first."
MSG_NOT_CONFIGURED = (
    "The Tellescope profile link is not set up. An admin can set "
    "TELLESCOPE_API_KEY or TELLESCOPE_PROFILE_URL_TEMPLATE in the plugin settings."
)
MSG_BAD_API_URL = "The TELLESCOPE_API_URL setting must be an https URL."
MSG_AUTH = (
    "Tellescope did not accept the API key. Ask an admin to check TELLESCOPE_API_KEY."
)
MSG_UNREACHABLE = "Could not reach Tellescope. Try again in a moment."
MSG_API_ERROR = "Tellescope returned an error. Try again in a moment."
MSG_NOT_LINKED = (
    "No linked Tellescope profile was found for this patient. "
    "Check that the patient has been synced to Tellescope."
)


class TellescopeLookupError(Exception):
    """A lookup failure with the fixed message to show in the pane."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _message(text: str) -> Effect:
    # Only fixed strings from this module reach here, so no escaping is needed.
    return LaunchModalEffect(
        content=f"<p>{text}</p>",
        target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        title=TITLE,
    ).apply()


def enduser_filter(patient_id: str) -> dict[str, Any]:
    """Tellescope Mongo-style filter for the enduser linked to a Canvas patient."""
    return {
        "$or": [
            {"$and": [{"source": "Canvas"}, {"externalId": patient_id}]},
            {"references": {"$elemMatch": {"type": "Canvas", "id": patient_id}}},
        ]
    }


def _first_enduser_id(body: Any) -> str | None:
    """Return the id of the first enduser in a list or {"data": [...]} body."""
    if isinstance(body, dict):
        body = body.get("data")
    if not isinstance(body, list) or not body:
        return None
    first = body[0]
    if not isinstance(first, dict):
        return None
    enduser_id = first.get("id") or first.get("_id")
    if not isinstance(enduser_id, str) or not enduser_id.strip():
        return None
    return enduser_id.strip()


def lookup_profile_url(api_key: str, api_url: str, patient_id: str) -> str:
    """Find the linked enduser through the Tellescope API and return its profile URL.

    Raises TellescopeLookupError with the message to show on any failure.
    """
    if not api_url.lower().startswith("https://"):
        log.warning(f"{API_URL_SETTING} is not an https URL; not calling Tellescope")
        raise TellescopeLookupError(MSG_BAD_API_URL)

    query = urlencode({"mdbFilter": json.dumps(enduser_filter(patient_id))})
    url = f"{api_url.rstrip('/')}/endusers?{query}"
    try:
        response = Http().get(
            url,
            headers={
                "Authorization": f"API_KEY {api_key}",
                "Content-Type": "application/json",
            },
        )
    except RequestException as exc:
        log.warning(
            f"Tellescope lookup for patient {patient_id} failed: {exc.__class__.__name__}"
        )
        raise TellescopeLookupError(MSG_UNREACHABLE) from exc

    status = response.status_code
    if status in (401, 403):
        log.warning(f"Tellescope lookup for patient {patient_id}: status {status}")
        raise TellescopeLookupError(MSG_AUTH)
    if status >= 400:
        log.warning(f"Tellescope lookup for patient {patient_id}: status {status}")
        raise TellescopeLookupError(MSG_API_ERROR)

    try:
        body = response.json()
    except ValueError as exc:
        log.warning(
            f"Tellescope lookup for patient {patient_id}: response was not JSON"
        )
        raise TellescopeLookupError(MSG_API_ERROR) from exc

    enduser_id = _first_enduser_id(body)
    if enduser_id is None:
        log.info(f"No Tellescope enduser linked to patient {patient_id}")
        raise TellescopeLookupError(MSG_NOT_LINKED)

    log.info(
        f"Opening Tellescope profile for patient {patient_id} -> enduser {enduser_id}"
    )
    return PROFILE_BASE_URL + quote(enduser_id, safe="")


class TellescopeProfileApp(Application):
    """Patient chart app that opens the patient's Tellescope profile."""

    def on_open(self) -> Effect:
        """Open the profile in the large right chart pane, or show why not."""
        patient = self.event.context.get("patient") or {}
        patient_id = str(patient.get("id") or "").strip()
        if not patient_id:
            return _message(MSG_NO_PATIENT)

        api_key = (self.secrets.get(API_KEY_SETTING) or "").strip()
        if api_key:
            api_url = (
                self.secrets.get(API_URL_SETTING) or ""
            ).strip() or DEFAULT_API_URL
            try:
                url = lookup_profile_url(api_key, api_url, patient_id)
            except TellescopeLookupError as exc:
                return _message(exc.message)
        else:
            template_url = template_profile_url(self.secrets, patient_id)
            if template_url is None:
                return _message(MSG_NOT_CONFIGURED)
            url = template_url

        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
            title=TITLE,
        ).apply()
