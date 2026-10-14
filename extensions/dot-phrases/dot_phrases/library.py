"""Reading and writing phrases, practice info, and settings."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.v1.data import Calendar, Note, Patient, Staff, Team
from django.db.models import F, Q

from dot_phrases.models import Phrase, PhraseFavorite, PhraseHidden, PracticeSetting, PracticeValue
from dot_phrases.text import pronouns

SETTING_DEFAULTS: dict[str, Any] = {"allow_copy_text": True}


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


def local_today(
    patient: Patient | None, note: Note | None, zone_name: str | None = None, owner_dbid: int | None = None
) -> date:
    """Today's date where the provider is, for {today} and {age}.

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
            return datetime.now(zone).date()
    return datetime.now(UTC).date()


def placeholder_values(
    patient: Patient | None,
    note: Note | None,
    today: date | None = None,
    zone_name: str | None = None,
    owner_dbid: int | None = None,
) -> dict[str, str]:
    """Patient placeholder values for one chart, plus the practice info values.

    Anything the chart has no value for is left out, so its placeholder stays as typed.
    """
    today = today or local_today(patient, note, zone_name, owner_dbid)
    values: dict[str, str] = dict(practice_values())
    values["today"] = today.strftime("%m/%d/%Y")
    if patient is not None:
        values["first_name"] = patient.first_name or ""
        values["preferred_name"] = patient.nickname or ""
        values["last_name"] = patient.last_name or ""
        values["age"] = _age(patient.birth_date, today)
        values["dob"] = patient.birth_date.strftime("%m/%d/%Y") if patient.birth_date else ""
        found = pronouns(getattr(patient, "preferred_pronouns", None))
        if found:
            values["subject_pronoun"], values["object_pronoun"], values["possessive_pronoun"] = found
    if note is not None:
        values["provider"] = staff_name(getattr(note, "provider", None))
    return {key: value for key, value in values.items() if value}


def phrase_fits_rx(phrase: Phrase, field: str) -> bool:
    """Whether a phrase is set up for a prescription field (sig or note_to_pharmacist)."""
    return bool(phrase.rx_sig) if field == "sig" else bool(phrase.rx_note_to_pharmacist)

