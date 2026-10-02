"""Server-side validation for waitlist entry submissions.

Every rule the browser enforces is re-checked here. The client-side copy exists
to give quick feedback, not to be trusted: both the chart form and the roster
post to the same endpoint, and a request can be made without either.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from canvas_sdk.v1.data import Patient, PracticeLocation, Staff

from scheduling_waitlist.constants import (
    MAX_NOTE_LENGTH,
    PREFERENCE_ANY,
    PREFERENCE_SPECIFIC,
)
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.options import (
    list_appointment_types,
    time_window_by_value,
    windows_for_value,
)


class ValidationResult:
    """Cleaned values, or the reasons they were refused."""

    def __init__(self, cleaned: dict[str, Any], errors: dict[str, str]):
        self.cleaned = cleaned
        self.errors = errors

    @property
    def ok(self) -> bool:
        return not self.errors


def _text(payload: dict, key: str) -> str:
    value = payload.get(key)
    return "" if value is None else str(value).strip()


def expiry_for(config: WaitlistConfig, today: date) -> date | None:
    """The last day a new entry stays live, or ``None`` when no shelf life is set."""
    if not config.ttl_days:
        return None
    return today + timedelta(days=config.ttl_days)


def validate_entry(
    payload: dict,
    *,
    config: WaitlistConfig,
    today: date,
    require_patient: bool = True,
) -> ValidationResult:
    """Check a create or edit submission.

    ``require_patient`` is off for edits, where the patient is fixed and must
    not be reassigned by a request body.
    """
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}

    if require_patient:
        patient_id = _text(payload, "patient_id")
        if not patient_id:
            errors["patient_id"] = "Choose a patient."
        else:
            patient = Patient.objects.filter(id=patient_id).first()
            if patient is None:
                errors["patient_id"] = "That patient could not be found."
            else:
                cleaned["patient_id"] = getattr(patient, "dbid", None)

    _clean_appointment_type(payload, config, cleaned, errors)
    _clean_provider(payload, cleaned, errors)
    _clean_location(payload, cleaned, errors)
    _clean_priority(payload, config, cleaned, errors)
    _clean_window(payload, cleaned, errors)

    note = _text(payload, "note")
    if len(note) > MAX_NOTE_LENGTH:
        errors["note"] = f"Keep the note under {MAX_NOTE_LENGTH} characters."
    else:
        cleaned["note"] = note

    if require_patient:
        cleaned["expires_on"] = expiry_for(config, today)

    return ValidationResult(cleaned, errors)


def _clean_appointment_type(
    payload: dict, config: WaitlistConfig, cleaned: dict, errors: dict
) -> None:
    raw = _text(payload, "appointment_type_id")
    if not raw:
        errors["appointment_type_id"] = "Choose a service."
        return

    # "Any service" is a real answer, and until now the only one the form could
    # not give: the column is nullable precisely so an entry can match every
    # type, and both the serializer and the banner already render that state. A
    # form that offered no such option left the service field defaulting to
    # whichever bookable type sorted first, so an entry could be created for a
    # service nobody books -- and it then matched nothing, silently.
    #
    # Kept distinct from a missing value on purpose: a blank field is a broken
    # client, not a preference.
    if raw == PREFERENCE_ANY:
        cleaned["note_type_id"] = None
        return

    # Checked against exactly what the form was offered, rather than re-deriving
    # the rule from configuration. Deriving it twice is what made the dropdown
    # list services this function then refused, so there is deliberately only
    # one implementation of "may be waitlisted" and it lives in options.
    offered = {
        str(option["dbid"]): option
        for option in list_appointment_types(config)
        if option["dbid"] is not None
    }

    if not offered:
        # No plugin setting can fix this: the instance has nothing bookable.
        errors["appointment_type_id"] = (
            "No appointment types on this instance can be scheduled."
        )
        return

    match = offered.get(str(raw))
    if match is None:
        # Either not bookable, or excluded by a configured allow-list. A stale or
        # tampered form lands here rather than writing an unbookable entry.
        errors["appointment_type_id"] = "That service is not offered on the waitlist."
        return

    cleaned["note_type_id"] = match["dbid"]


def _clean_provider(payload: dict, cleaned: dict, errors: dict) -> None:
    preference = _text(payload, "provider_preference") or PREFERENCE_SPECIFIC
    if preference == PREFERENCE_ANY:
        cleaned["provider_preference"] = PREFERENCE_ANY
        cleaned["desired_provider_id"] = None
        return

    raw = _text(payload, "provider_id")
    if not raw:
        errors["provider_id"] = "Choose a provider, or select any provider."
        return

    provider = Staff.objects.filter(dbid=raw, active=True).first()
    if provider is None:
        errors["provider_id"] = "That provider is not available."
        return

    cleaned["provider_preference"] = PREFERENCE_SPECIFIC
    cleaned["desired_provider_id"] = getattr(provider, "dbid", None)


def _clean_location(payload: dict, cleaned: dict, errors: dict) -> None:
    preference = _text(payload, "location_preference") or PREFERENCE_SPECIFIC
    if preference == PREFERENCE_ANY:
        cleaned["location_preference"] = PREFERENCE_ANY
        cleaned["desired_location_id"] = None
        return

    raw = _text(payload, "location_id")
    if not raw:
        errors["location_id"] = "Choose a location, or select any location."
        return

    location = PracticeLocation.objects.filter(dbid=raw, active=True).first()
    if location is None:
        errors["location_id"] = "That location is not available."
        return

    cleaned["location_preference"] = PREFERENCE_SPECIFIC
    cleaned["desired_location_id"] = getattr(location, "dbid", None)


def _clean_priority(payload: dict, config: WaitlistConfig, cleaned: dict, errors: dict) -> None:
    label = _text(payload, "priority") or config.default_priority_label
    if not config.is_known_priority(label):
        errors["priority"] = "Choose one of the configured priorities."
        return
    cleaned["priority_label"] = label
    cleaned["priority_rank"] = config.priority_rank(label)


def _clean_window(payload: dict, cleaned: dict, errors: dict) -> None:
    value = _text(payload, "preferred_window") or "any"
    if time_window_by_value(value) is None:
        errors["preferred_window"] = "Choose one of the offered time windows."
        return

    cleaned["preferred_windows"] = windows_for_value(value)
    cleaned["preferred_windows_timezone"] = _text(payload, "preferred_window_timezone")
    cleaned["preferred_window_note"] = _text(payload, "preferred_window_note")[
        :MAX_NOTE_LENGTH
    ]
