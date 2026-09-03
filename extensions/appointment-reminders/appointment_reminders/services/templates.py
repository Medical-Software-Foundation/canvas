"""Template rendering for notification messages."""
import json
import zoneinfo
from datetime import datetime
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.organization import Organization
from canvas_sdk.v1.data.patient import Patient

from appointment_reminders.services.business_line import (
    get_business_line_name,
    resolve_attribution,
)
from appointment_reminders.services.timezones import zone_for_address

_DEFAULT_TZ_NAME = "America/New_York"
_ORG_VARS_CACHE_KEY = "appointment_reminders:org_vars"
_ORG_VARS_CACHE_TTL = 300  # 5 minutes — matches cron interval


def _format_phone(raw: str) -> str:
    """Render a stored phone number for a patient to read.

    Contact points hold bare digits, so an unformatted value reaches the patient
    as "Call 8005550199". Formats North American numbers and returns anything
    else unchanged rather than mangling an international number.
    """
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) != 10:
        return raw or ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _business_line_vars(patient: Patient, config: Any = None) -> dict[str, str]:
    """Business-line placeholders, shared across all campaign variable sets.

    ``{{business_line}}`` is the raw name (read straight off the patient);
    ``{{business_line_attribution}}`` is the resolved patient-facing phrase and
    needs ``config`` for its per-business-line override / default fallback. When
    ``config`` is omitted, attribution renders empty.
    """
    name = get_business_line_name(patient)
    attribution = resolve_attribution(config, name) if config is not None else ""
    return {"business_line": name, "business_line_attribution": attribution}


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Render a template string by replacing {{variable}} placeholders."""
    result = template
    for key, value in variables.items():
        placeholder = f"{{{{{key}}}}}"
        result = result.replace(placeholder, str(value))
    return result


def unresolved_placeholders(text: str) -> list[str]:
    """Return the ``{{placeholder}}`` names left unreplaced in rendered text.

    A non-empty result means the message would reach the patient with literal
    template syntax in it, so callers refuse the send rather than deliver it.
    Parsed by hand instead of with a regex to keep the plugin sandbox's import
    surface unchanged.
    """
    found: list[str] = []
    rest = text
    while "{{" in rest:
        _, _, rest = rest.partition("{{")
        name, closed, rest = rest.partition("}}")
        if not closed:
            break
        name = name.strip()
        if name and name not in found:
            found.append(name)
    return found


def _patient_address_timezone(patient: Patient) -> str:
    """The zone implied by the patient's address, or ``""`` if none resolves.

    Filters the addresses in Python rather than with ``.filter()`` so the
    reminder cron's prefetch still pays off, the same reason the location block
    in ``_build_variables`` does. Prefers an active home address, then any
    active one, then whatever is on file — a patient whose only address is
    marked inactive still lives somewhere.
    """
    addresses = getattr(patient, "addresses", None)
    if addresses is None:
        return ""

    rows = list(addresses.all())
    ordered = (
        [a for a in rows if a.use == "home" and a.state == "active"]
        + [a for a in rows if a.state == "active"]
        + rows
    )
    for address in ordered:
        zone = zone_for_address(
            getattr(address, "state_code", "") or "",
            getattr(address, "postal_code", "") or "",
            getattr(address, "country", "") or "",
        )
        if zone:
            return zone
    return ""


def resolve_timezone_name(patient: Patient, clinic_timezone: str = "") -> str:
    """The IANA zone name a patient's times should be rendered and sent in.

    Order: the timezone explicitly recorded on the patient, then the zone
    implied by their address, then the configured clinic default, then Eastern.
    The address step is what makes this resolve at all in practice — see
    ``services/timezones.py`` for why ``last_known_timezone`` is almost always
    empty.

    Each candidate is type-checked before ``ZoneInfo`` sees it, because
    ``last_known_timezone`` is free text and a non-string would raise a
    ``TypeError`` the loop is not otherwise catching.
    """
    # Each candidate is a callable so the address lookup is skipped entirely
    # when the patient already carries an explicit zone.
    candidates = (
        lambda: getattr(patient, "last_known_timezone", None),
        lambda: _patient_address_timezone(patient),
        lambda: clinic_timezone,
        lambda: _DEFAULT_TZ_NAME,
    )
    for candidate in candidates:
        tz_str = candidate()
        if not tz_str or not isinstance(tz_str, str):
            continue
        try:
            zoneinfo.ZoneInfo(tz_str)
        except (KeyError, ValueError):
            continue
        return tz_str
    return _DEFAULT_TZ_NAME


def _resolve_timezone(patient: Patient, clinic_timezone: str = "") -> zoneinfo.ZoneInfo:
    """Resolve display timezone: patient → patient address → clinic → Eastern."""
    return zoneinfo.ZoneInfo(resolve_timezone_name(patient, clinic_timezone))


def _tz_abbrev(dt: datetime) -> str:
    """Return a short timezone abbreviation like 'ET', 'CT', 'PT'."""
    abbrev = dt.strftime("%Z")  # e.g. "EST", "EDT", "CST", "CDT"
    # Shorten standard US abbreviations: EST/EDT→ET, CST/CDT→CT, etc.
    _SHORT = {
        "EST": "ET", "EDT": "ET",
        "CST": "CT", "CDT": "CT",
        "MST": "MT", "MDT": "MT",
        "PST": "PT", "PDT": "PT",
        "AKST": "AKT", "AKDT": "AKT",
        "HST": "HT",
    }
    return _SHORT.get(abbrev, abbrev)


def _format_date(local_dt: datetime) -> str:
    """Format a date without a zero-padded day: 'August 5, 2026'."""
    return f"{local_dt.strftime('%B')} {local_dt.day}, {local_dt.year}"


def _format_time(local_dt: datetime) -> str:
    """Format a time without a zero-padded hour: '3:40 PM'."""
    return f"{local_dt.hour % 12 or 12}:{local_dt.strftime('%M %p')}"


def get_template_variables(
    patient: Patient,
    appointment: Appointment,
    clinic_timezone: str = "",
    config: Any = None,
) -> dict[str, str]:
    """Extract template variables from patient and appointment.

    Pass ``config`` to resolve ``{{business_line_attribution}}`` (per-business-line
    override → default). ``{{business_line}}`` resolves without it.
    """
    meeting_link = ""
    if getattr(appointment, "meeting_link", None):
        meeting_link = appointment.meeting_link
    return _build_variables(
        patient,
        appointment.start_time,
        appointment.provider,
        appointment.location,
        meeting_link,
        appointment.description or "",
        clinic_timezone,
        config,
    )


def get_note_template_variables(
    patient: Patient,
    note: Any,
    clinic_timezone: str = "",
    config: Any = None,
) -> dict[str, str]:
    """Extract template variables from patient and a standalone note.

    A note has no appointment row and therefore no ``meeting_link``, so
    ``{{telehealth_link}}`` resolves from the provider's personal meeting room,
    the same fallback the appointment path already uses.

    Routing notes through the shared builder is what stops the two manual-send
    paths from drifting. Hand-building a shorter dict here previously left
    ``{{telehealth_link}}`` and ``{{business_line_attribution}}`` unreplaced in
    the delivered message, and rendered the time in UTC with no zone label.
    """
    return _build_variables(
        patient,
        note.datetime_of_service,
        note.provider,
        note.location,
        "",
        note.title or "",
        clinic_timezone,
        config,
    )


def _build_variables(
    patient: Patient,
    start_time: datetime | None,
    provider: Any,
    location: Any,
    meeting_link: str,
    description: str,
    clinic_timezone: str = "",
    config: Any = None,
) -> dict[str, str]:
    """Build the full placeholder set from already-resolved parts.

    Shared by the appointment and standalone-note paths so both render the same
    placeholders in the same timezone. ``start_time`` may be ``None`` (a note
    without a service datetime), in which case date and time render empty rather
    than raising.
    """
    appointment_date = ""
    appointment_time = ""
    if start_time is not None:
        tz = _resolve_timezone(patient, clinic_timezone)
        local_start = start_time.astimezone(tz)
        appointment_date = _format_date(local_start)
        appointment_time = f"{_format_time(local_start)} {_tz_abbrev(local_start)}"

    provider_name = "your provider"
    credentials = ""
    if provider:
        provider_name = f"{provider.first_name} {provider.last_name}"
        # Build credentials: role public abbreviations (matches home app name_and_roles pattern)
        try:
            abbrevs = [
                r.public_abbreviation
                for r in provider.roles.all()
                if r.public_abbreviation
            ]
            credentials = ", ".join(abbrevs)
        except Exception:
            pass

    location_name = "our clinic"
    if location:
        location_name = location.full_name

    # Resolve telehealth link: appointment meeting_link → provider meeting room
    telehealth_link = ""
    if meeting_link:
        telehealth_link = meeting_link
    elif provider and hasattr(provider, "personal_meeting_room_link"):
        telehealth_link = provider.personal_meeting_room_link or ""

    # --- Practice location variables (from the appointment or note location) ---
    loc_full_name = location_name
    loc_short_name = ""
    loc_address = ""
    loc_phone = ""
    if location:
        loc = location
        loc_full_name = loc.full_name or location_name
        loc_short_name = loc.short_name or ""
        # Filter the prefetched `addresses` in Python so the reminder-cron
        # prefetch actually pays off (a .filter() here would re-query per send).
        _addrs = list(loc.addresses.all())
        loc_addr = next((a for a in _addrs if a.use == "work" and a.state == "active"), None)
        if not loc_addr:
            loc_addr = next((a for a in _addrs if a.state == "active"), None)
        if loc_addr:
            parts = [loc_addr.line1]
            if loc_addr.line2:
                parts.append(loc_addr.line2)
            parts.append(f"{loc_addr.city}, {loc_addr.state_code} {loc_addr.postal_code}")
            loc_address = ", ".join(parts)
        _tels = sorted(loc.telecom.all(), key=lambda t: t.rank or 0)
        loc_cp = next(
            (t for t in _tels if t.system == "phone" and t.use == "work" and t.state == "active"),
            None,
        )
        if not loc_cp:
            loc_cp = next((t for t in _tels if t.system == "phone" and t.state == "active"), None)
        if loc_cp:
            loc_phone = loc_cp.value or ""

    variables = {
        "patient_first_name": patient.first_name,
        "patient_last_name": patient.last_name,
        "patient_preferred_name": patient.preferred_first_name,
        "patient_name": patient.first_name,
        "patient_full_name": f"{patient.first_name} {patient.last_name}".strip(),
        "provider_name": provider_name,
        "credentials": credentials,
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "location_name": location_name,
        "appointment_type": description,
        "telehealth_link": telehealth_link,
        "location_full_name": loc_full_name,
        "location_short_name": loc_short_name,
        "location_address": loc_address,
        "location_phone": _format_phone(loc_phone),
    }
    variables.update(_get_org_variables())
    variables.update(_business_line_vars(patient, config))
    return variables


def _get_org_variables() -> dict[str, str]:
    """Fetch organization-level template variables.

    Cached for 5 minutes — org name/address/phone change rarely, and the cron
    schedulers call this once per appointment. Without the cache a 100-appointment
    cron iteration fires 300 redundant queries.
    """
    cache = get_cache()
    cached = cache.get(_ORG_VARS_CACHE_KEY)
    if cached:
        try:
            parsed: dict[str, str] = json.loads(cached)
            return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    org_full_name = ""
    org_short_name = ""
    org_address = ""
    org_phone = ""
    try:
        org = Organization.objects.first()
        if org:
            org_full_name = org.full_name or ""
            org_short_name = org.short_name or ""
            org_addr = org.addresses.filter(use="work", state="active").first()
            if org_addr:
                parts = [org_addr.line1]
                if org_addr.line2:
                    parts.append(org_addr.line2)
                parts.append(f"{org_addr.city}, {org_addr.state_code} {org_addr.postal_code}")
                org_address = ", ".join(parts)
            org_cp = (
                org.telecom.filter(system="phone", use="work", state="active")
                .order_by("rank")
                .first()
            )
            if org_cp:
                org_phone = org_cp.value or ""
    except Exception:
        pass
    result = {
        "organization_full_name": org_full_name,
        "organization_short_name": org_short_name,
        "organization_address": org_address,
        "organization_phone": _format_phone(org_phone),
    }
    try:
        cache.set(_ORG_VARS_CACHE_KEY, json.dumps(result), timeout_seconds=_ORG_VARS_CACHE_TTL)
    except Exception:
        pass
    return result


