"""Timezone utilities for preserving wall-clock time across DST changes."""

from enum import Enum
from typing import Any, cast
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data import Appointment as AppointmentModel, AppointmentMetadata
from canvas_sdk.v1.data.facility import Facility
from canvas_sdk.v1.data.patient import Patient
from logger import log

from facility_recurring_scheduler.utils.constants import (
    DEFAULT_TIMEZONE,
    FIELD_FACILITY_KEY,
)

# Sentinel distinguishing "no facility name supplied, look it up" from an
# explicit None ("looked up, none selected") so batch callers can skip the query.
# An Enum member is used rather than object() because the Canvas sandbox does not
# expose the `object` builtin.
class _Unset(Enum):
    TOKEN = 0


_UNSET: Any = _Unset.TOKEN


# Mapping of US state codes to their primary timezone
# For states spanning multiple timezones, uses the most populous timezone
STATE_TO_TIMEZONE = {
    # Eastern Time
    "CT": "America/New_York",
    "DE": "America/New_York",
    "DC": "America/New_York",
    "FL": "America/New_York",  # Most of FL is Eastern
    "GA": "America/New_York",
    "IN": "America/Indiana/Indianapolis",  # Most of IN is Eastern
    "KY": "America/New_York",  # Eastern part is more populous
    "ME": "America/New_York",
    "MD": "America/New_York",
    "MA": "America/New_York",
    "MI": "America/Detroit",
    "NH": "America/New_York",
    "NJ": "America/New_York",
    "NY": "America/New_York",
    "NC": "America/New_York",
    "OH": "America/New_York",
    "PA": "America/New_York",
    "RI": "America/New_York",
    "SC": "America/New_York",
    "VT": "America/New_York",
    "VA": "America/New_York",
    "WV": "America/New_York",
    # Central Time
    "AL": "America/Chicago",
    "AR": "America/Chicago",
    "IL": "America/Chicago",
    "IA": "America/Chicago",
    "KS": "America/Chicago",  # Most of KS is Central
    "LA": "America/Chicago",
    "MN": "America/Chicago",
    "MS": "America/Chicago",
    "MO": "America/Chicago",
    "NE": "America/Chicago",  # Most of NE is Central
    "ND": "America/Chicago",  # Most of ND is Central
    "OK": "America/Chicago",
    "SD": "America/Chicago",  # Most of SD is Central
    "TN": "America/Chicago",  # Most of TN is Central
    "TX": "America/Chicago",  # Most of TX is Central
    "WI": "America/Chicago",
    # Mountain Time
    "AZ": "America/Phoenix",  # No DST (except Navajo Nation)
    "CO": "America/Denver",
    "ID": "America/Boise",  # Most of ID is Mountain
    "MT": "America/Denver",
    "NM": "America/Denver",
    "UT": "America/Denver",
    "WY": "America/Denver",
    # Pacific Time
    "CA": "America/Los_Angeles",
    "NV": "America/Los_Angeles",  # Most of NV is Pacific
    "OR": "America/Los_Angeles",  # Most of OR is Pacific
    "WA": "America/Los_Angeles",
    # Alaska
    "AK": "America/Anchorage",
    # Hawaii
    "HI": "Pacific/Honolulu",  # No DST
    # Territories
    "AS": "Pacific/Pago_Pago",  # American Samoa
    "GU": "Pacific/Guam",
    "MP": "Pacific/Guam",  # Northern Mariana Islands
    "PR": "America/Puerto_Rico",
    "VI": "America/Puerto_Rico",  # US Virgin Islands
}


def get_timezone_from_state(state_code: str | None) -> ZoneInfo | None:
    """Get timezone from a US state code.

    Args:
        state_code: Two-letter US state code (e.g., "NY", "CA")

    Returns:
        ZoneInfo for the state's timezone, or None if not found
    """
    if not state_code:
        return None

    timezone_str = STATE_TO_TIMEZONE.get(state_code.upper())
    if timezone_str:
        return ZoneInfo(timezone_str)
    return None


def _facility_name_from_metadata(appointment: AppointmentModel) -> str | None:
    """Read the selected facility name from appointment metadata (single query)."""
    try:
        return cast(
            "str | None",
            AppointmentMetadata.objects.filter(
                appointment=appointment, key=FIELD_FACILITY_KEY
            ).values_list("value", flat=True).first(),
        )
    except Exception:
        log.warning(f"Failed to look up facility metadata for appointment {appointment.id}")
        return None


def _timezone_from_facility(
    facility_name: str | None,
    facility_state_by_name: dict[str, str | None] | None = None,
) -> ZoneInfo | None:
    """Resolve a timezone from a facility name via its state.

    If ``facility_state_by_name`` (a prefetched name→state_code map) is supplied,
    no query is issued; otherwise the matching Facility row is fetched.
    """
    if not facility_name:
        return None
    try:
        if facility_state_by_name is not None:
            state_code = facility_state_by_name.get(facility_name)
        else:
            facility = Facility.objects.filter(name=facility_name, active=True).first()
            state_code = facility.state_code if facility else None
        if state_code:
            return get_timezone_from_state(state_code)
    except Exception:
        log.warning(f"Failed to resolve timezone from facility {facility_name!r}")
    return None


def _timezone_from_patient(patient: "Patient | None") -> ZoneInfo | None:
    """Resolve a timezone from an already-loaded patient.

    Order: preferred (last_known) timezone, then primary address state.
    """
    if not patient:
        return None
    # Preferred / last known timezone
    try:
        if patient.last_known_timezone:
            # last_known_timezone should be a valid IANA timezone string
            return ZoneInfo(str(patient.last_known_timezone))
    except Exception:
        log.warning(f"Failed to resolve patient preferred timezone for patient {patient.id}")
    # Primary address state
    try:
        for address in patient.addresses.all():
            if address.state_code:
                tz = get_timezone_from_state(address.state_code)
                if tz:
                    return tz
    except Exception:
        log.warning(f"Failed to resolve timezone from patient address for patient {patient.id}")
    return None


def resolve_timezone(
    facility_name: str | None,
    patient: "Patient | None",
    *,
    facility_state_by_name: dict[str, str | None] | None = None,
) -> ZoneInfo:
    """Resolve a timezone from already-fetched inputs.

    Resolution order: facility state → patient preferred timezone → patient
    address state → DEFAULT_TIMEZONE. Performs no metadata or patient lookups of
    its own; the caller supplies the facility name and (optionally) a loaded
    patient, which lets batch callers avoid per-item queries.
    """
    return (
        _timezone_from_facility(facility_name, facility_state_by_name)
        or _timezone_from_patient(patient)
        or ZoneInfo(DEFAULT_TIMEZONE)
    )


def get_timezone_for_appointment(
    appointment: AppointmentModel,
    patient_id: str | None = None,
) -> ZoneInfo:
    """Get the timezone for an appointment based on facility or patient preference.

    Resolution order:
    1. Facility selected in appointment metadata → facility's state
    2. Patient's last_known_timezone (preferred scheduling timezone)
    3. Patient's primary address → patient's state
    4. DEFAULT_TIMEZONE fallback

    Args:
        appointment: The appointment model instance
        patient_id: Optional patient ID for fallback lookup

    Returns:
        ZoneInfo object for the appropriate timezone
    """
    facility_name = _facility_name_from_metadata(appointment)

    patient = None
    try:
        if patient_id:
            patient = Patient.objects.filter(id=patient_id).first()
    except Exception:
        log.warning(f"Failed to look up patient {patient_id} for timezone resolution")

    return resolve_timezone(facility_name, patient)


def get_timezone_for_location(
    appointment: AppointmentModel,
    *,
    facility_name: str | None = _UNSET,
    facility_state_by_name: dict[str, str | None] | None = None,
) -> ZoneInfo:
    """Get the timezone for an appointment, reusing its already-loaded patient.

    Unlike :func:`get_timezone_for_appointment`, this reads ``appointment.patient``
    directly rather than re-querying by id — callers that loaded the appointment
    with ``select_related("patient")`` pay nothing more. Batch callers may also
    pass a prefetched ``facility_name`` and ``facility_state_by_name`` map to skip
    the per-call metadata and Facility lookups entirely.

    Args:
        appointment: The appointment model instance
        facility_name: Prefetched facility name; omit to read from metadata
        facility_state_by_name: Prefetched name→state_code map; omit to query

    Returns:
        ZoneInfo object for the appropriate timezone
    """
    if facility_name is _UNSET:
        facility_name = _facility_name_from_metadata(appointment)

    patient = None
    try:
        patient = appointment.patient
    except Exception:
        log.warning(f"Failed to access patient for appointment {appointment.id}")

    return resolve_timezone(
        facility_name, patient, facility_state_by_name=facility_state_by_name
    )
