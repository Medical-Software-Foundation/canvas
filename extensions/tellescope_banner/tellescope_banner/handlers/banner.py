"""Chart banner that links to the patient's Tellescope profile.

The link is built from the TELLESCOPE_PROFILE_URL_TEMPLATE setting. The
template may use two placeholders:

- ``{patient_id}``: the Canvas patient id (the patient key).
- ``{external_id}``: the value of the patient's external identifier whose
  system matches TELLESCOPE_IDENTIFIER_SYSTEM.

The patient value is URL-encoded before it goes into the link. If the
template is missing or invalid, or the patient has no matching identifier,
the plugin shows no banner and removes one it showed before (fail closed).
"""

import re
from typing import ClassVar
from urllib.parse import quote

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.patient import PatientExternalIdentifier
from logger import log

BANNER_KEY = "tellescope-profile"
NARRATIVE = "Open this patient's Tellescope profile"

TEMPLATE_SETTING = "TELLESCOPE_PROFILE_URL_TEMPLATE"
SYSTEM_SETTING = "TELLESCOPE_IDENTIFIER_SYSTEM"

PATIENT_ID = "patient_id"
EXTERNAL_ID = "external_id"
ALLOWED_PLACEHOLDERS = frozenset({PATIENT_ID, EXTERNAL_ID})

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")

PATIENT_EVENTS = frozenset(
    {
        EventType.PATIENT_CREATED,
        EventType.PATIENT_UPDATED,
    }
)


def template_placeholders(template: str) -> set[str] | None:
    """Return the placeholders a template uses, or None if it is not usable.

    A usable template is an https URL with at least one placeholder, only
    known placeholders, and no stray braces.
    """
    if not template.lower().startswith("https://"):
        return None
    names = set(_PLACEHOLDER.findall(template))
    if not names or not names <= ALLOWED_PLACEHOLDERS:
        return None
    rest = _PLACEHOLDER.sub("", template)
    if "{" in rest or "}" in rest:
        return None
    return names


def build_profile_url(template: str, values: dict[str, str]) -> str:
    """Fill the template, URL-encoding every value (including '/')."""
    return _PLACEHOLDER.sub(
        lambda match: quote(values[match.group(1)], safe=""), template
    )


class TellescopeProfileBanner(BaseHandler):
    """Adds, refreshes or removes the Tellescope banner when a patient changes."""

    RESPONDS_TO: ClassVar[list[str]] = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.PATIENT_EXTERNAL_IDENTIFIER_CREATED),
        EventType.Name(EventType.PATIENT_EXTERNAL_IDENTIFIER_UPDATED),
        EventType.Name(EventType.PATIENT_EXTERNAL_IDENTIFIER_DELETED),
    ]

    def _patient_id(self) -> str | None:
        if self.event.type in PATIENT_EVENTS:
            return self.event.target.id or None
        patient = self.event.context.get("patient") or {}
        return patient.get("id") or None

    def compute(self) -> list[Effect]:
        """Return one banner effect (add or remove) for the patient."""
        patient_id = self._patient_id()
        if not patient_id:
            return []

        url = self._profile_url(patient_id)
        if url is None:
            return [RemoveBannerAlert(patient_id=patient_id, key=BANNER_KEY).apply()]

        return [
            AddBannerAlert(
                patient_id=patient_id,
                key=BANNER_KEY,
                narrative=NARRATIVE,
                placement=[
                    AddBannerAlert.Placement.CHART,
                    AddBannerAlert.Placement.PROFILE,
                ],
                intent=AddBannerAlert.Intent.INFO,
                href=url,
            ).apply()
        ]

    def _profile_url(self, patient_id: str) -> str | None:
        template = (self.secrets.get(TEMPLATE_SETTING) or "").strip()
        if not template:
            log.warning(f"{TEMPLATE_SETTING} is not set; showing no Tellescope banner")
            return None

        placeholders = template_placeholders(template)
        if placeholders is None:
            log.warning(
                f"{TEMPLATE_SETTING} must be an https URL that uses only "
                "{patient_id} and/or {external_id}; showing no Tellescope banner"
            )
            return None

        values = {PATIENT_ID: patient_id}
        if EXTERNAL_ID in placeholders:
            external_id = self._external_id(patient_id)
            if not external_id:
                return None
            values[EXTERNAL_ID] = external_id

        return build_profile_url(template, values)

    def _external_id(self, patient_id: str) -> str | None:
        system = (self.secrets.get(SYSTEM_SETTING) or "").strip()
        if not system:
            log.warning(
                f"{TEMPLATE_SETTING} uses {{external_id}} but {SYSTEM_SETTING} is not set; "
                "showing no Tellescope banner"
            )
            return None

        # A patient has only a handful of identifiers, so skip blank or
        # whitespace-only values in Python and keep the newest real one.
        values = (
            PatientExternalIdentifier.objects.filter(
                patient__id=patient_id, system=system
            )
            .order_by("-modified")
            .values_list("value", flat=True)
        )
        for value in values:
            if value and value.strip():
                return value.strip()
        return None
