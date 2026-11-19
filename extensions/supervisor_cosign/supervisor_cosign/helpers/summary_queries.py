"""The two views behind the co-sign summary page.

``mode=records`` lists ``CoSignRecord`` rows — exactly what needs attesting and
what is already done. ``mode=notes`` lists the supervisees' notes themselves,
so a supervisor can see the denominator: what was written versus what the
sampler picked up.

Every function here returns plain dicts and runs a fixed number of queries,
independent of page size. The N+1 to avoid is concrete: ``api/handlers.py``
has ``_staff_name`` and ``_staff_credentialed_name``, each one query, and a
row loop is exactly where someone reaches for them.
"""

from datetime import date, timedelta

from django.db.models import Count

from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteType, NoteStates
from canvas_sdk.v1.data.staff import Staff

from supervisor_cosign.helpers.note_links import note_chart_url
from supervisor_cosign.helpers.note_type_codes import (
    normalize_note_type_code,
    parse_cosign_note_type_codes,
)
from supervisor_cosign.helpers.supervision import supervised_staff
from supervisor_cosign.models.cosign_record import CoSignRecord

#: Unbounded, ``mode=notes`` is "every note ever written by every supervisee".
#: The window is applied server-side whenever the caller omits one, so a
#: hand-rolled request cannot ask for everything by leaving a param off.
DEFAULT_WINDOW_DAYS = 30

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

#: Ceiling on the note ids materialised to compute the notes-mode summary.
#: ``CoSignRecord.note_id`` is a TextField with no FK, so there is no join that
#: could count approved-vs-pending in the database -- the ids have to come back
#: to Python. Past this many notes the strip is marked partial rather than
#: quietly under-reporting.
SUMMARY_SCAN_CAP = 2000

#: A Canvas ``Note`` is not only a chart note — it is also the row behind
#: appointments, messages, letters and data imports. Left unfiltered, a team's
#: 30 days is mostly appointment stubs, and the unsigned encounter notes a
#: supervisor opened this page to find are buried. Encounter, appointment,
#: inpatient, review and letter stay in; these come out unless asked for.
NON_CLINICAL_CATEGORIES = ("message", "data", "task", "schedule_event", "ccda")

#: Never shown. A compliance view that lists deleted notes invites somebody to
#: go chasing a note that is not there.
ALWAYS_EXCLUDED_STATES = (NoteStates.DELETED,)

#: Off by default: a cancelled or no-show booking was never going to carry an
#: attestation.
CANCELLED_STATES = (NoteStates.CANCELLED, NoteStates.NOSHOW)


def clamp_limit(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if value < 1:
        return DEFAULT_LIMIT
    return min(value, MAX_LIMIT)


def clamp_offset(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def window_bounds(start_str: str, end_str: str) -> tuple[str, str]:
    """The date window to query, defaulting to the last 30 days.

    Returned as ISO strings because both callers hand them straight to a
    ``__date__gte``/``__lte`` lookup, which accepts them as-is.
    """
    end = _parse_date(end_str) or date.today()
    start = _parse_date(start_str) or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
    if start > end:
        start = end
    return start.isoformat(), end.isoformat()


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def eligible_note_type_codes(secrets) -> list[str]:
    """The raw ``NoteType.code`` values matching ``COSIGN_NOTE_TYPE_CODES``.

    The configured list is compared after normalization (case folded,
    separators dropped), which SQL cannot reproduce — so resolve the codes
    once against the note-type table and filter on the raw values. Filtering a
    fetched page in Python instead would produce short pages and broken
    paging.

    Filtering is on ``code``, never on ``NoteType.id``:
    ``canvas_sdk_data_api_notetype_001`` is a view where one ``id`` can return
    several versioned rows, so an ``id__in`` join can multiply a note.
    ``note_type_version`` points at the row's primary key, which does not.
    """
    wanted = parse_cosign_note_type_codes(secrets)
    if not wanted:
        return []
    codes = set()
    for code in NoteType.objects.values_list("code", flat=True):
        if code and normalize_note_type_code(code) in wanted:
            codes.add(code)
    return sorted(codes)


def _excluded_state_note_pks(include_cancelled: bool):
    """Note PKs to exclude, as a subquery rather than a join.

    ``CurrentNoteStateEvent.note`` is declared ``OneToOneField`` over
    ``canvas_sdk_data_current_note_state_001``, which is a database **view**
    and enforces no uniqueness. ``Note.objects.exclude(current_state__state__in=...)``
    therefore compiles to a LEFT OUTER JOIN that multiplies each note by its
    state history — the shape that numbered a patient's 5th note as #17.
    ``tests/test_note_state_join.py`` is the executable record; the subquery
    form below is the fix it pins.
    """
    states = list(ALWAYS_EXCLUDED_STATES)
    if not include_cancelled:
        states = states + list(CANCELLED_STATES)
    return CurrentNoteStateEvent.objects.filter(state__in=states).values_list(
        "note_id", flat=True
    )


def note_states_by_id(note_ids: list[str]) -> dict:
    """``{note uuid: state}`` for one page of notes, in one query.

    Read separately for the same reason ``_excluded_state_note_pks`` is a
    subquery: the view can hand back more than one row per note, and a
    ``select_related`` would duplicate the note rather than the state.
    """
    if not note_ids:
        return {}
    states = {}
    rows = CurrentNoteStateEvent.objects.filter(note__id__in=note_ids).values(
        "note__id", "state"
    )
    for row in rows:
        states[str(row["note__id"])] = row["state"]
    return states


def _name(first, last) -> str:
    return (str(first or "") + " " + str(last or "")).strip()


def hydrate_staff(staff_ids) -> dict:
    """``{staff id: display name}`` for a set of ids, in one query."""
    wanted = [sid for sid in set(staff_ids) if sid]
    if not wanted:
        return {}
    names = {}
    for row in Staff.objects.filter(id__in=wanted).values("id", "first_name", "last_name"):
        names[str(row["id"])] = _name(row["first_name"], row["last_name"])
    return names


def _iso(value):
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    if isoformat is None:
        return str(value)
    return isoformat()


def records_rows(role: dict, params: dict, secrets) -> dict:
    """``mode=records`` — the co-sign records themselves.

    Scope is applied before any request parameter is read: a plain supervisor
    is pinned to their own records and the ``supervisor`` filter is discarded,
    so putting somebody else's key in the URL yields nothing rather than
    widening the view.
    """
    start, end = window_bounds(params.get("start"), params.get("end"))
    limit = clamp_limit(params.get("limit"))
    offset = clamp_offset(params.get("offset"))

    qs = CoSignRecord.objects.all()
    if role["oversight"]:
        supervisor_filter = str(params.get("supervisor") or "").strip()
        if supervisor_filter:
            qs = qs.filter(supervisor_id=supervisor_filter)
    else:
        qs = qs.filter(supervisor_id=role["staff_id"])

    supervisee_filter = str(params.get("supervisee") or "").strip()
    if supervisee_filter:
        qs = qs.filter(supervisee_id=supervisee_filter)

    status_filter = str(params.get("status") or "").strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    qs = qs.filter(selected_at__date__gte=start, selected_at__date__lte=end)

    # Before slicing. The strip is a compliance figure, so it has to describe
    # the whole filtered set -- computed off the page it would move as you
    # page, which is exactly how a coverage number gets misread.
    summary, total = _summarize_records(qs)

    # Fetch one extra to answer has_more without a COUNT over the table.
    page = list(
        qs.order_by("-selected_at", "-dbid").values(
            "note_id",
            "supervisee_id",
            "supervisor_id",
            "status",
            "selected_at",
            "due_date",
            "cosigned_at",
        )[offset : offset + limit + 1]
    )
    has_more = len(page) > limit
    page = page[:limit]

    note_ids = [str(r["note_id"]) for r in page if r["note_id"]]
    notes = _notes_by_id(note_ids)
    states = note_states_by_id(note_ids)
    staff_ids = []
    for r in page:
        staff_ids.append(str(r["supervisee_id"] or ""))
        staff_ids.append(str(r["supervisor_id"] or ""))
    # The strip names supervisees who may not appear on this page, so hydrate
    # the union -- still one query.
    for sid in summary:
        staff_ids.append(sid)
    names = hydrate_staff(staff_ids)

    rows = []
    for r in page:
        note_id = str(r["note_id"] or "")
        note = notes.get(note_id, {})
        supervisor_id = str(r["supervisor_id"] or "")
        rows.append(
            {
                "note_id": note_id,
                "note_date": _iso(note.get("datetime_of_service")),
                "patient_name": _name(
                    note.get("patient__first_name"), note.get("patient__last_name")
                ),
                "note_type": note.get("note_type_version__name") or "",
                "note_url": note_chart_url(note.get("patient__id"), note.get("dbid")),
                "note_state": states.get(note_id, ""),
                "supervisee_id": str(r["supervisee_id"] or ""),
                "supervisee_name": names.get(str(r["supervisee_id"] or ""), ""),
                "supervisor_id": supervisor_id,
                "supervisor_name": names.get(supervisor_id, ""),
                "status": r["status"] or "",
                "due_date": _iso(r["due_date"]),
                "cosigned_at": _iso(r["cosigned_at"]),
                "selected_at": _iso(r["selected_at"]),
                "can_cosign": r["status"] == "pending"
                and supervisor_id == role["staff_id"],
            }
        )
    for sid in summary:
        summary[sid]["name"] = names.get(sid, "")
    return {
        "rows": rows,
        "has_more": has_more,
        "start": start,
        "end": end,
        "offset": offset,
        "limit": limit,
        "total": total,
        "summary": summary,
        "summary_partial": False,
    }


def _summarize_records(qs) -> tuple[dict, int]:
    """Per-supervisee counts over the whole filtered set, as a GROUP BY.

    Exact and cheap: the database does the counting and hands back one row per
    (supervisee, status) pair, so nothing scales with how many records match.
    Names are filled in by the caller, which is already hydrating staff.
    """
    summary: dict = {}
    total = 0
    for row in qs.values("supervisee_id", "status").annotate(n=Count("dbid")):
        sid = str(row["supervisee_id"] or "")
        if not sid:
            continue
        count = int(row["n"] or 0)
        counts = summary.get(sid)
        if counts is None:
            counts = {"name": "", "total": 0, "approved": 0, "pending": 0}
            summary[sid] = counts
        # Plain assignment, never ``+=`` on a subscript: the sandbox rejects an
        # augmented subscript at module load and blanks every template.
        counts["total"] = counts["total"] + count
        if row["status"] == "approved":
            counts["approved"] = counts["approved"] + count
        elif row["status"] == "pending":
            counts["pending"] = counts["pending"] + count
        total = total + count
    _add_percentages(summary)
    return summary, total


def _add_percentages(summary: dict) -> None:
    for key in summary:
        counts = summary[key]
        seen = counts["total"]
        counts["pct_cosigned"] = round(counts["approved"] / seen * 100, 1) if seen else 0


def _notes_by_id(note_ids: list[str]) -> dict:
    """``{note uuid: note field dict}`` in one query.

    ``CoSignRecord`` stores ``note_id`` as a ``TextField``, not a ForeignKey
    (a deliberate choice — FK ``to_field="dbid"`` plus ``filter(fk__id=uuid)``
    is broken in ``CustomModel``), so there is no join to reach for here and
    the lookup has to be by set.
    """
    if not note_ids:
        return {}
    notes = {}
    rows = Note.objects.filter(id__in=note_ids).values(
        "id",
        # dbid, not id: the chart deep link keys on the integer dbid and
        # silently ignores the UUID. See helpers/note_links.note_chart_url.
        "dbid",
        "datetime_of_service",
        "patient__id",
        "patient__first_name",
        "patient__last_name",
        "note_type_version__name",
        "note_type_version__code",
    )
    for row in rows:
        notes[str(row["id"])] = row
    return notes


def notes_rows(role: dict, params: dict, secrets) -> dict:
    """``mode=notes`` — every supervisee note in the window.

    Four queries: the team, the excluded-state subquery folded into the note
    page, the note page itself, and the co-sign records for those notes.
    Supervisee and supervisor names come off the team list already in hand.
    """
    start, end = window_bounds(params.get("start"), params.get("end"))
    limit = clamp_limit(params.get("limit"))
    offset = clamp_offset(params.get("offset"))
    include_cancelled = _flag(params.get("include_cancelled"))
    include_non_clinical = _flag(params.get("include_non_clinical"))

    if role["oversight"]:
        supervisor_filter = str(params.get("supervisor") or "").strip()
        supervisor_ids = [supervisor_filter] if supervisor_filter else None
    else:
        supervisor_ids = [role["staff_id"]]

    team = supervised_staff(supervisor_ids)
    supervisee_filter = str(params.get("supervisee") or "").strip()
    if supervisee_filter:
        # Validated against the caller's own team, so a supervisee key that is
        # not theirs narrows to nothing instead of widening the scope.
        team = [s for s in team if s["id"] == supervisee_filter]
    if not team:
        return {
            "rows": [], "has_more": False, "start": start, "end": end,
            "offset": offset, "limit": limit, "total": 0,
            "summary": {}, "summary_partial": False,
        }

    by_supervisee = {}
    for member in team:
        by_supervisee[member["id"]] = member

    qs = Note.objects.filter(
        provider__id__in=list(by_supervisee.keys()),
        datetime_of_service__date__gte=start,
        datetime_of_service__date__lte=end,
    ).exclude(pk__in=_excluded_state_note_pks(include_cancelled))

    if not include_non_clinical:
        qs = qs.exclude(note_type_version__category__in=NON_CLINICAL_CATEGORIES)

    if _flag(params.get("eligible_only")):
        codes = eligible_note_type_codes(secrets)
        if codes:
            qs = qs.filter(note_type_version__code__in=codes)

    summary, total, summary_partial = _summarize_notes(qs, by_supervisee)

    page = list(
        qs.order_by("-datetime_of_service", "-dbid").values(
            "id",
            "dbid",
            "datetime_of_service",
            "provider__id",
            "patient__id",
            "patient__first_name",
            "patient__last_name",
            "note_type_version__name",
        )[offset : offset + limit + 1]
    )
    has_more = len(page) > limit
    page = page[:limit]

    note_ids = [str(n["id"]) for n in page]
    states = note_states_by_id(note_ids)
    records = _records_by_note_id(note_ids)

    rows = []
    for n in page:
        note_id = str(n["id"])
        member = by_supervisee.get(str(n["provider__id"] or ""), {})
        record = records.get(note_id, {})
        supervisor_id = str(record.get("supervisor_id") or member.get("supervisor_id") or "")
        rows.append(
            {
                "note_id": note_id,
                "note_date": _iso(n["datetime_of_service"]),
                "patient_name": _name(n["patient__first_name"], n["patient__last_name"]),
                "note_type": n["note_type_version__name"] or "",
                "note_url": note_chart_url(n["patient__id"], n["dbid"]),
                "note_state": states.get(note_id, ""),
                "supervisee_id": str(n["provider__id"] or ""),
                "supervisee_name": member.get("name", ""),
                "supervisor_id": supervisor_id,
                "supervisor_name": member.get("supervisor_name", ""),
                "status": record.get("status") or "",
                "due_date": _iso(record.get("due_date")),
                "cosigned_at": _iso(record.get("cosigned_at")),
                "selected_at": _iso(record.get("selected_at")),
                "can_cosign": record.get("status") == "pending"
                and supervisor_id == role["staff_id"],
            }
        )
    return {
        "rows": rows,
        "has_more": has_more,
        "start": start,
        "end": end,
        "offset": offset,
        "limit": limit,
        "total": total,
        "summary": summary,
        "summary_partial": summary_partial,
    }


def _summarize_notes(qs, by_supervisee: dict) -> tuple[dict, int, bool]:
    """Per-supervisee coverage over the whole filtered set of notes.

    Totals come from a GROUP BY, so they are exact however many notes match.
    Approved-vs-pending cannot: ``CoSignRecord.note_id`` is a TextField with no
    ForeignKey (see ``_notes_by_id``), so there is no join and the note ids
    have to come back to Python to be matched. That pass is capped at
    ``SUMMARY_SCAN_CAP``; past it the caller is told the split is partial
    rather than being handed a number that silently under-counts.

    Names come off ``by_supervisee``, which the caller already fetched.
    """
    summary: dict = {}
    total = 0
    for row in qs.values("provider__id").annotate(n=Count("dbid")):
        sid = str(row["provider__id"] or "")
        if not sid:
            continue
        count = int(row["n"] or 0)
        member = by_supervisee.get(sid, {})
        summary[sid] = {
            "name": member.get("name", ""),
            "total": count,
            "approved": 0,
            "pending": 0,
        }
        total = total + count

    scanned = list(qs.values_list("id", "provider__id")[:SUMMARY_SCAN_CAP])
    partial = total > len(scanned)
    provider_by_note = {}
    for note_id, provider_id in scanned:
        provider_by_note[str(note_id)] = str(provider_id or "")

    records = _records_by_note_id(list(provider_by_note.keys()))
    for note_id in records:
        sid = provider_by_note.get(note_id, "")
        counts = summary.get(sid)
        if counts is None:
            continue
        status = records[note_id].get("status")
        if status == "approved":
            counts["approved"] = counts["approved"] + 1
        elif status == "pending":
            counts["pending"] = counts["pending"] + 1

    _add_percentages(summary)
    return summary, total, partial


def _records_by_note_id(note_ids: list[str]) -> dict:
    """``{note uuid: record}``, approved beating pending.

    Same precedence as ``protocols/cosign_button.py``: if a co-sign was
    completed, show that even when a stale pending row survives alongside it,
    so the page and the note-header button can never disagree about a note.
    """
    if not note_ids:
        return {}
    records = {}
    rows = CoSignRecord.objects.filter(note_id__in=note_ids).values(
        "note_id", "supervisor_id", "status", "due_date", "cosigned_at", "selected_at"
    )
    for row in rows:
        key = str(row["note_id"])
        existing = records.get(key)
        if existing is None or (
            existing.get("status") != "approved" and row["status"] == "approved"
        ):
            records[key] = row
    return records


def _flag(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")
