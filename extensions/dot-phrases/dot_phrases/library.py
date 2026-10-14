"""Reading and writing phrases, practice info, and settings."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from canvas_sdk.v1.data import Note, Patient, Staff, Team
from django.db.models import F, Q

from dot_phrases.catalog import RX_FIELDS
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
    for phrase in Phrase.objects.filter(query, archived=False).select_related("owner"):
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


def placeholder_values(patient: Patient | None, note: Note | None, today: date | None = None) -> dict[str, str]:
    """Patient placeholder values for one chart, plus the practice info values.

    Anything the chart has no value for is left out, so its placeholder stays as typed.
    """
    today = today or datetime.now(UTC).date()
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


def rx_field_max(field: str) -> int:
    """The character limit for a prescription field."""
    return RX_FIELDS[field][1]
