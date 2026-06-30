"""Schedule-derived group session discovery.

A group session is the set of appointments that share the same provider and the
exact same ``start_time`` and carry a Group Therapy reason for visit, with 2+
patients. The documenter picks a date; the plugin lists that day's group
sessions and their rosters (each attendee's existing appointment note is the
documentation target). Canvas exposes no per-appointment RFV on the SDK
Appointment model, so the group reason is read from each appointment note's
``reasonForVisit`` command coding (normalized match against the configured
codes).
"""

from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import CurrentNoteStateEvent
from canvas_sdk.v1.data.patient import Patient
from logger import log

# Note state codes (NoteStates values). Literals, not the enum, so comparison
# against the raw stored code works in the runtime and under the SDK stub.
# Already in an editable encounter state - document directly. Mirrors the SDK's
# CurrentNoteStateEvent.editable() set (NEW, CVD, PSH, ULK, RST, UND).
_DOCUMENTABLE_STATES = {"NEW", "CVD", "ULK", "RST", "PSH", "UND"}
# A scheduled appointment note that must be checked in before documentation.
_CHECKIN_STATES = {"BKD", "SCH"}


def _normalize(value: str) -> str:
    """Lowercase and strip separators so 'Group_Therapy' == 'Group Therapy'."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _appointment_rows(session_date) -> list[dict]:
    """One joined query of the day's live appointments (excludes cancelled / errored)."""
    return list(
        Appointment.objects.filter(start_time__date=session_date)
        .exclude(status=AppointmentProgressStatus.CANCELLED)
        .filter(entered_in_error_id__isnull=True)
        .values(
            "start_time",
            "duration_minutes",
            "provider__id",
            "provider__first_name",
            "provider__last_name",
            "patient__id",
            "patient__first_name",
            "patient__last_name",
            "patient__birth_date",
            "note_id",
            "note__id",
        )
    )


def _group_note_codes(note_dbids: list, rfv_codes: list[str]) -> dict:
    """Map note dbid -> the configured group RFV code its reasonForVisit matched."""
    if not note_dbids:
        return {}
    norm_to_code = {}
    for code in rfv_codes:
        norm_to_code.setdefault(_normalize(code), code)
    matched: dict = {}
    commands = Command.objects.filter(
        note_id__in=note_dbids, schema_key="reasonForVisit", entered_in_error_id__isnull=True
    )
    for command in commands:
        coding = (command.data or {}).get("coding") or {}
        for form in (coding.get("value"), coding.get("text"), coding.get("code")):
            if form and _normalize(form) in norm_to_code:
                matched[command.note_id] = norm_to_code[_normalize(form)]
                break
    return matched


def _documented_note_dbids(note_dbids: list) -> set:
    """Note dbids that already have a group therapy summary command.

    Plugin custom commands carry a per-install hash suffix (e.g.
    ``groupTherapyNote_0ac95acc``), so match the schema_key by prefix.
    """
    if not note_dbids:
        return set()
    return set(
        Command.objects.filter(
            note_id__in=note_dbids,
            schema_key__startswith="groupTherapyNote",
            entered_in_error_id__isnull=True,
        ).values_list("note_id", flat=True)
    )


def _note_states_by_dbid(note_dbids: list) -> dict:
    """Map note dbid -> current note state code (e.g. 'BKD', 'CVD', 'LKD')."""
    if not note_dbids:
        return {}
    rows = CurrentNoteStateEvent.objects.filter(note_id__in=note_dbids).values_list(
        "note_id", "state"
    )
    return {note_id: state for note_id, state in rows}


def _patient_photos(patient_ids: list) -> dict:
    """Map patient id (UUID) -> presigned avatar URL, for patients with a real photo.

    Uses the SDK ``photo`` relation to detect a real uploaded photo (vs the
    default avatar) and ``photo_url`` for the presigned S3 link. Returns {} if
    the SDK version does not expose patient photos.
    """
    if not patient_ids:
        return {}
    photos: dict = {}
    try:
        for patient in Patient.objects.filter(id__in=patient_ids):
            if patient.photo:
                photos[str(patient.id)] = patient.photo_url
    except (AttributeError, ValueError, TypeError) as exc:
        log.warning(f"patient photo lookup failed: {exc}")
    return photos


def _initials(first: str, last: str) -> str:
    return ((first or "")[:1] + (last or "")[:1]).upper()


def find_group_sessions(session_date, rfv_codes: list[str]) -> list[dict]:
    """Return the date's group sessions, each with provider, time, RFV codes, and
    roster. The matched ``rfv_codes`` resolve the configured template (and its CPT)
    downstream - that template is the single source of truth for session type.
    """
    try:
        rows = _appointment_rows(session_date)
        note_dbids = [r["note_id"] for r in rows if r.get("note_id")]
        group_codes = _group_note_codes(note_dbids, rfv_codes)
        group_dbids = set(group_codes)
        note_states = _note_states_by_dbid(note_dbids)
        documented_dbids = _documented_note_dbids(note_dbids)
        photos = _patient_photos(
            [r["patient__id"] for r in rows if r.get("note_id") in group_dbids and r.get("patient__id")]
        )
    except (AttributeError, ValueError, TypeError) as exc:
        log.warning(f"find_group_sessions failed for date={session_date}: {exc}")
        return []

    grouped: dict = {}
    for row in rows:
        if row.get("note_id") not in group_dbids:
            continue
        key = (row["provider__id"], row["start_time"])
        grouped.setdefault(key, []).append(row)

    sessions: list[dict] = []
    for (provider_uuid, start_time), members in grouped.items():
        if len(members) < 2:
            continue
        head = members[0]
        provider_name = (
            f"{head.get('provider__first_name') or ''} "
            f"{head.get('provider__last_name') or ''}"
        ).strip()
        roster = []
        for m in members:
            birth_date = m.get("patient__birth_date")
            dob = birth_date.strftime("%m/%d/%Y") if birth_date else ""
            state = note_states.get(m.get("note_id"))
            needs_checkin = state in _CHECKIN_STATES
            documentable = state in _DOCUMENTABLE_STATES
            patient_uuid = str(m["patient__id"])
            roster.append(
                {
                    "patient_id": patient_uuid,
                    "name": (
                        f"{m.get('patient__first_name') or ''} "
                        f"{m.get('patient__last_name') or ''}"
                    ).strip(),
                    "initials": _initials(
                        m.get("patient__first_name"), m.get("patient__last_name")
                    ),
                    "dob": dob,
                    "photo_url": photos.get(patient_uuid, ""),
                    "note_id": str(m.get("note__id") or ""),
                    "note_state": str(state or ""),
                    "needs_checkin": needs_checkin,
                    # marked no-show (NSW) - not documentable, but not "signed/locked" either
                    "noshow": state == "NSW",
                    # not actionable (no-show, locked, signed, cancelled, etc.)
                    "blocked": not needs_checkin and not documentable,
                    # already has a group therapy summary - re-documenting duplicates
                    "documented": m.get("note_id") in documented_dbids,
                }
            )
        roster.sort(key=lambda x: x["name"])
        start = start_time.isoformat() if hasattr(start_time, "isoformat") else str(start_time)
        # the matched group RFV code(s) for this slot - used to resolve the
        # configured template (GET /template?rfv=) downstream
        session_codes = sorted({group_codes.get(m.get("note_id"), "") for m in members} - {""})
        sessions.append(
            {
                "provider_id": str(provider_uuid),
                "provider_name": provider_name,
                "start_time": start,
                "rfv_codes": session_codes,
                # facilitator + duration come from the appointment, not free entry
                "facilitator": provider_name,
                "duration_minutes": head.get("duration_minutes") or "",
                "patient_count": len(roster),
                "roster": roster,
            }
        )
    sessions.sort(key=lambda s: s["start_time"])
    return sessions
