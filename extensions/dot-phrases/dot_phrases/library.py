"""Reading and writing phrases, practice info, and settings."""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.v1.data import (
    Appointment,
    BusinessLine,
    Calendar,
    Coverage,
    Note,
    Patient,
    PatientFacilityAddress,
    PatientMetadata,
    Staff,
    Team,
)
from canvas_sdk.v1.data.reason_for_visit import ReasonForVisit
from django.db.models import F, Q

from dot_phrases.models import Phrase, PhraseFavorite, PhraseHidden, PracticeSetting, PracticeValue
from dot_phrases.text import CHART_OFF_BY_DEFAULT, PATIENT_PLACEHOLDERS, pronouns

SETTING_DEFAULTS: dict[str, Any] = {"allow_copy_text": True}

# Placeholders that each need their own lookup, so they are only looked up when a phrase uses them.
_LOOKUPS: dict[str, frozenset[str]] = {
    "business_line": frozenset({"business_line"}),
    "facility": frozenset({"facility", "room_number"}),
    "location": frozenset({"practice_location"}),
    "visits": frozenset({"last_visit", "next_visit"}),
    "coverage": frozenset({"insurance", "plan", "member_id", "group_number"}),
}


def admin_team_name(secrets: dict[str, Any] | None) -> str:
    """The Canvas team whose members manage practice phrases, from the ADMIN_TEAM setting."""
    return str((secrets or {}).get("ADMIN_TEAM") or "").strip()


def is_admin(staff_id: str | None, secrets: dict[str, Any] | None) -> bool:
    """Whether a staff member (by Staff id) is on the admin team.

    Fails closed: when the setting is empty, or no team has that name, nobody is an admin.
    """
    team = admin_team_name(secrets)
    if not staff_id or not team:
        return False
    return bool(Team.objects.filter(name__iexact=team, members__id=str(staff_id)).exists())


def staff_dbid(staff_id: str | None) -> int | None:
    """Look up a staff member's database id from their Staff id."""
    if not staff_id:
        return None
    dbid: int | None = Staff.objects.filter(id=staff_id).values_list("dbid", flat=True).first()
    return dbid


def usable_phrases(owner_dbid: int | None) -> dict[str, Phrase]:
    """The phrases one staff member can use, by code.

    Practice phrases plus the staff member's own personal phrases. A personal phrase with the same
    code as a practice phrase is used instead of it.
    """
    query = Q(scope="practice")
    if owner_dbid is not None:
        query |= Q(scope="personal", owner_id=owner_dbid)
    by_code: dict[str, Phrase] = {}
    # Oldest first, so if a code was ever saved twice the same row always wins.
    for phrase in Phrase.objects.filter(query, archived=False).select_related("owner").order_by("dbid"):
        current = by_code.get(phrase.code)
        if current is None or (phrase.scope == "personal" and current.scope == "practice"):
            by_code[phrase.code] = phrase
    return by_code


def favorite_ids(owner_dbid: int | None) -> set[int]:
    """The phrases a staff member starred."""
    if owner_dbid is None:
        return set()
    return set(PhraseFavorite.objects.filter(staff_id=owner_dbid).values_list("phrase_id", flat=True))


def hidden_ids(owner_dbid: int | None) -> set[int]:
    """The practice phrases a staff member hid from their list."""
    if owner_dbid is None:
        return set()
    return set(PhraseHidden.objects.filter(staff_id=owner_dbid).values_list("phrase_id", flat=True))


def practice_values() -> dict[str, str]:
    """Practice info placeholders and their values."""
    return {row.name: row.value for row in PracticeValue.objects.all()}


def custom_placeholders() -> dict[str, str]:
    """Admin-made patient placeholders: placeholder name to the patient metadata key it reads."""
    value = get_setting("custom_placeholders")
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def known_names() -> set[str]:
    """Placeholder names that aren't chart placeholders: practice info and custom patient ones."""
    return set(practice_values()) | set(custom_placeholders())


def enabled_chart_placeholders() -> list[str]:
    """Chart placeholders the practice shows in the editor's menus, in list order."""
    value = get_setting("chart_placeholders")
    chosen = set(value) if isinstance(value, list) else set(PATIENT_PLACEHOLDERS) - CHART_OFF_BY_DEFAULT
    return [name for name in PATIENT_PLACEHOLDERS if name in chosen]


def get_setting(key: str) -> Any:
    """A practice-wide setting, or its default."""
    row = PracticeSetting.objects.filter(key=key).first()
    if row is None or row.value is None:
        return SETTING_DEFAULTS.get(key)
    return row.value


def set_setting(key: str, value: Any) -> None:
    """Save a practice-wide setting."""
    PracticeSetting.objects.update_or_create(key=key, defaults={"value": value})


def record_use(phrase_ids: list[int]) -> None:
    """Count a use, for the Recently used and Most used sorts."""
    if phrase_ids:
        Phrase.objects.filter(dbid__in=phrase_ids).update(uses=F("uses") + 1, last_used_at=datetime.now(UTC))


def _age(birth_date: date | None, today: date) -> str:
    if not birth_date:
        return ""
    years = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    return str(max(years, 0))


def staff_name(staff: Any) -> str:
    """A staff member's name as it reads in a note."""
    if staff is None:
        return ""
    parts = [getattr(staff, "first_name", "") or "", getattr(staff, "last_name", "") or ""]
    return " ".join(p for p in parts if p).strip()


def _zone(value: Any) -> ZoneInfo | None:
    """A time zone from a stored value: a zone object or a name like "America/Chicago"."""
    name = str(value or "").strip()
    if not name:
        return None
    try:
        # A stored zone object prints as its name, so both forms go through ZoneInfo.
        return ZoneInfo(name)
    except (KeyError, ValueError):
        # ZoneInfoNotFoundError is a KeyError; a malformed name is a ValueError.
        return None


def _tz_key(staff_dbid: int) -> str:
    return f"dot-phrases:tz:{staff_dbid}"


def remember_timezone(staff_dbid: int | None, name: str | None) -> str | None:
    """Keep the time zone a staff member's browser reported, so their typed codes use it too.

    Returns the zone name when it's a real time zone, or None. Stored in the plugin cache, which
    keeps it for up to 14 days; each chart panel open refreshes it.
    """
    zone = _zone(name)
    if zone is None:
        return None
    if staff_dbid is not None:
        get_cache().set(_tz_key(staff_dbid), str(zone))
    return str(zone)


def remembered_timezone(staff_dbid: int | None) -> str | None:
    """The last time zone a staff member's browser reported, if the cache still has it."""
    if staff_dbid is None:
        return None
    value = get_cache().get(_tz_key(staff_dbid))
    return str(value) if value else None


def calendar_timezone() -> str | None:
    """The time zone most of the instance's calendars use, checked at most once a day."""
    cache = get_cache()
    cached = cache.get("dot-phrases:calendar-tz")
    if cached is not None:
        return str(cached) or None
    counts: dict[str, int] = {}
    for value in Calendar.objects.values_list("timezone", flat=True)[:5000]:
        name = str(value or "")
        if name and name != "UTC":
            counts[name] = counts.get(name, 0) + 1
    best = max(counts, key=lambda k: counts[k]) if counts else ""
    cache.set("dot-phrases:calendar-tz", best, timeout_seconds=86400)
    return best or None


def local_zone(
    patient: Patient | None, note: Note | None, zone_name: str | None = None, owner_dbid: int | None = None
) -> timezone | ZoneInfo:
    """The time zone the provider is in, for {today}, {age}, and visit times.

    Canvas gives plugins no practice time zone. In order, this uses: the browser's time zone (for
    the chart panel), the time zone the command creator's browser last reported, the note
    provider's and then the patient's saved Canvas time zone, the time zone most calendars use,
    and only then UTC.
    """
    candidates = (
        lambda: zone_name,
        lambda: remembered_timezone(owner_dbid),
        lambda: getattr(getattr(note, "provider", None), "last_known_timezone", None),
        lambda: getattr(patient, "last_known_timezone", None),
        calendar_timezone,
    )
    for candidate in candidates:
        zone = _zone(candidate())
        if zone is not None:
            return zone
    return UTC


def local_today(
    patient: Patient | None, note: Note | None, zone_name: str | None = None, owner_dbid: int | None = None
) -> date:
    """Today's date where the provider is (see local_zone)."""
    return datetime.now(local_zone(patient, note, zone_name, owner_dbid)).date()


def _reason_for_visit_title(note: Note) -> str:
    """The text of the note's first recorded reason for visit, which Canvas uses as the note's heading.

    For a coded reason Canvas uses the code's name, and only falls back to the comment when there's
    no code. A practice setting can make Canvas use the last reason instead, and plugins can't read
    it, so a note with two reasons can differ.
    """
    for rfv in ReasonForVisit.objects.committed().filter(note_id=note.dbid).prefetch_related("codings").order_by("dbid"):
        codings = list(rfv.codings.all())
        text = str(codings[-1].display or "").strip() if codings else ""
        if not text:
            text = str(ReasonForVisit.string_from_narrative_json(rfv.narrative_json) or "").strip()
        if text:
            return text
    return ""


def note_label(note: Note) -> dict[str, Any]:
    """Title, visit time, and provider of a note, as the chart panel's "Adding to" line shows it.

    The title follows the note heading: the reason for visit, then the note's title, then its type.
    """
    version = getattr(note, "note_type_version", None)
    title = _reason_for_visit_title(note) or getattr(note, "title", "") or (getattr(version, "name", "") if version else "") or "Note"
    when = getattr(note, "datetime_of_service", None)
    return {
        "title": title,
        # A timestamp, so the browser shows the date in the user's time zone, as the note header does.
        "when": when.isoformat() if when else "",
        "provider": staff_name(getattr(note, "provider", None)),
    }


def _joined(items: list[str]) -> str:
    """ "A", "A and B", or "A, B, and C"."""
    items = [i for i in items if i]
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _visit_time(when: datetime, zone: timezone | ZoneInfo) -> str:
    local = when.astimezone(zone)
    hour = local.hour % 12 or 12
    return f"{local:%m/%d/%Y} at {hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"


def _facility_values(patient: Patient) -> dict[str, str]:
    # Canvas has no current facility: it shows every active facility address, so all are listed.
    rows = PatientFacilityAddress.objects.filter(patient=patient, state="active").select_related("facility").order_by("dbid")
    names = [str(getattr(r.facility, "name", "") or "") for r in rows if r.facility is not None]
    rooms = [str(r.room_number or "") for r in rows if r.facility is not None]
    return {"facility": _joined(names), "room_number": _joined(rooms)}


def _visit_values(patient: Patient, note: Note | None, zone: timezone | ZoneInfo) -> dict[str, str]:
    """The last visit before this note and the next one scheduled, skipping cancelled and no-shows."""
    now = datetime.now(UTC)
    reference = getattr(note, "datetime_of_service", None) or now
    moved = Appointment.objects.filter(patient=patient, appointment_rescheduled_from__isnull=False).values(
        "appointment_rescheduled_from_id"
    )
    visits = (
        Appointment.objects.filter(patient=patient, entered_in_error__isnull=True)
        .exclude(status__in=["cancelled", "noshowed"])
        .exclude(dbid__in=moved)
    )
    if note is not None:
        visits = visits.exclude(note_id=note.dbid)
    last = visits.filter(start_time__lt=reference).order_by("-start_time").values_list("start_time", flat=True).first()
    upcoming = visits.filter(start_time__gt=max(reference, now)).order_by("start_time").values_list("start_time", flat=True).first()
    return {
        "last_visit": _visit_time(last, zone) if last else "",
        "next_visit": _visit_time(upcoming, zone) if upcoming else "",
    }


def _coverage_values(patient: Patient, on: date) -> dict[str, str]:
    # The same coverage Canvas shows as a note's primary: rank 1, in use, and in date on the visit day.
    coverage = (
        Coverage.objects.filter(patient=patient, coverage_rank=1, stack="IN_USE", coverage_start_date__lte=on)
        .filter(Q(coverage_end_date__isnull=True) | Q(coverage_end_date__gte=on))
        .select_related("issuer")
        .order_by("dbid")
        .first()
    )
    if coverage is None:
        return {}
    return {
        "insurance": str(getattr(coverage.issuer, "name", "") or ""),
        "plan": str(coverage.plan or ""),
        "member_id": str(coverage.id_number or ""),
        "group_number": str(coverage.group or ""),
    }


def placeholder_values(
    patient: Patient | None,
    note: Note | None,
    today: date | None = None,
    zone_name: str | None = None,
    owner_dbid: int | None = None,
    needed: set[str] | None = None,
    practice: dict[str, str] | None = None,
    custom: dict[str, str] | None = None,
) -> dict[str, str]:
    """Chart placeholder values for one chart, plus practice info and custom patient placeholders.

    Anything the chart has no value for is left out, so its placeholder stays as typed. Pass the
    placeholder names a phrase uses as `needed` to skip lookups nothing will use and return only
    those values; None looks up and returns all. Pass practice info and custom placeholders when the
    caller already read them, so they aren't read twice.
    """
    zone = local_zone(patient, note, zone_name, owner_dbid)
    today = today or datetime.now(zone).date()

    def wanted(group: str) -> bool:
        return needed is None or bool(needed & _LOOKUPS[group])

    values: dict[str, str] = dict(practice_values() if practice is None else practice)
    values["today"] = today.strftime("%m/%d/%Y")
    if patient is not None:
        values["first_name"] = patient.first_name or ""
        values["preferred_name"] = patient.nickname or ""
        values["last_name"] = patient.last_name or ""
        values["age"] = _age(patient.birth_date, today)
        values["dob"] = patient.birth_date.strftime("%m/%d/%Y") if patient.birth_date else ""
        values["mrn"] = str(getattr(patient, "mrn", "") or "")
        found = pronouns(getattr(patient, "preferred_pronouns", None))
        if found:
            values["subject_pronoun"], values["object_pronoun"], values["possessive_pronoun"] = found
        if wanted("business_line") and getattr(patient, "business_line_id", None):
            values["business_line"] = str(BusinessLine.objects.filter(dbid=patient.business_line_id).values_list("name", flat=True).first() or "")
        if wanted("facility"):
            values.update(_facility_values(patient))
        if wanted("visits"):
            values.update(_visit_values(patient, note, zone))
        if wanted("coverage"):
            visit_day = note.datetime_of_service.astimezone(zone).date() if note is not None and note.datetime_of_service else today
            values.update(_coverage_values(patient, visit_day))
        custom = custom_placeholders() if custom is None else custom
        if needed is not None:
            custom = {name: key for name, key in custom.items() if name in needed}
        if custom:
            stored = dict(PatientMetadata.objects.filter(patient=patient, key__in=set(custom.values())).values_list("key", "value"))
            for name, key in custom.items():
                values[name] = str(stored.get(key) or "")
    if note is not None:
        values["provider"] = staff_name(getattr(note, "provider", None))
        if wanted("location") and getattr(note, "location_id", None):
            values["practice_location"] = str(getattr(note.location, "full_name", "") or "")
    return {key: value for key, value in values.items() if value and (needed is None or key.lower() in needed)}


def phrase_fits_rx(phrase: Phrase, field: str) -> bool:
    """Whether a phrase is set up for a prescription field (sig or note_to_pharmacist)."""
    return bool(phrase.rx_sig) if field == "sig" else bool(phrase.rx_note_to_pharmacist)

