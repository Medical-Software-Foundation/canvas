"""Chart-Closure Queue SimpleAPI handler.

Serves the HTML shell, static assets, and JSON data for the open-notes worklist.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

# Open / unsigned states — a note in any of these still needs to be locked.
# This mirrors CurrentNoteStateEvent.editable(): the note can still be edited,
# i.e. the documentation loop is not yet closed. Locked/signed/deleted and the
# appointment-lifecycle states are deliberately excluded.
_OPEN_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]

# Friendly, provider-facing labels for each open state.
_STATE_LABELS: dict[str, str] = {
    NoteStates.NEW.value: "New",
    NoteStates.PUSHED.value: "Charges pushed",
    NoteStates.CONVERTED.value: "Checked in",
    NoteStates.UNLOCKED.value: "Unlocked",
    NoteStates.RESTORED.value: "Restored",
    NoteStates.UNDELETED.value: "Undeleted",
}

# Default aging thresholds (in days open) when the secrets are unset/invalid.
_DEFAULT_AMBER_DAYS = 2
_DEFAULT_RED_DAYS = 4


class ClosureAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the chart-closure queue modal UI and data.

    Routes:
        GET /          – HTML shell (index.html)
        GET /main.js   – JavaScript asset
        GET /styles.css – CSS asset
        GET /data      – JSON list of the provider's open/unsigned notes
    """

    PREFIX = "/app"

    # ── Static asset routes ───────────────────────────────────────────────

    @api.get("/")
    def get_index(self) -> list[Response | Effect]:
        """Serve the HTML shell for the modal."""
        html = render_to_string(
            "templates/index.html",
            context={"cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html or "", status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def get_js(self) -> list[Response | Effect]:
        """Serve the JavaScript asset."""
        return [
            Response(
                (render_to_string("static/main.js") or "").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the CSS asset."""
        return [
            Response(
                (render_to_string("static/styles.css") or "").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    # ── Data route ────────────────────────────────────────────────────────

    @api.get("/data")
    def get_data(self) -> list[Response | Effect]:
        """Return the logged-in provider's open/unsigned notes, oldest first.

        Query parameters:
            end (str): ISO-8601 datetime for the end of the provider's local
                "today". Notes with a date of service after this are excluded
                (future-scheduled). The date portion is also used as the
                reference point for the "days open" aging calculation.

        Fails closed: returns 400 (and no data) when the non-spoofable staff
        UUID header is missing, so a request can never fall through to an
        all-provider query.
        """
        staff_uuid = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_uuid:
            return [
                JSONResponse(
                    {"error": "Missing canvas-logged-in-user-id header"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        end_str = self.request.query_params.get("end")
        if not end_str:
            return [
                JSONResponse(
                    {"error": "Query parameter 'end' is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            end_dt = datetime.fromisoformat(end_str)
        except ValueError:
            return [
                JSONResponse(
                    {"error": "Query parameter 'end' is not a valid ISO-8601 datetime"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        amber_days = _parse_threshold(
            self.secrets.get("AGING_AMBER_DAYS"), _DEFAULT_AMBER_DAYS
        )
        red_days = _parse_threshold(
            self.secrets.get("AGING_RED_DAYS"), _DEFAULT_RED_DAYS
        )

        events = _fetch_open_state_events(staff_uuid, end_dt)

        ref_date = end_dt.date()
        ref_tz = end_dt.tzinfo
        notes = [
            _build_row(event, ref_date, ref_tz, amber_days, red_days)
            for event in events
        ]

        return [JSONResponse({"notes": notes})]


# ── Data access ─────────────────────────────────────────────────────────────


def _fetch_open_state_events(staff_uuid: str, end_dt: datetime):  # type: ignore[no-untyped-def]  # pragma: no cover
    """Return open-note CurrentNoteStateEvents for one provider, oldest first.

    A single bulk query with select_related across the note's patient,
    note-type version, and provider — constant query count, no N+1 and no
    per-note follow-ups.

    Coverage: this thin ORM wrapper is exercised by the real-DB factory tests
    in ``test_closure_api`` (django_db); the unit tests patch it.
    """
    return (
        CurrentNoteStateEvent.objects.filter(
            state__in=_OPEN_STATES,
            note__provider__id=staff_uuid,
            note__datetime_of_service__lte=end_dt,
        )
        .select_related("note__patient", "note__note_type_version", "note__provider")
        .order_by("note__datetime_of_service")
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _parse_threshold(raw: str | None, default: int) -> int:
    """Parse a secret value into a positive int, falling back to ``default``.

    Unset, non-numeric, or negative values all fall back to the default rather
    than corrupting the aging buckets.
    """
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError):
        return default
    return value if value >= 0 else default


def _aging_level(days_open: int, amber_days: int, red_days: int) -> str:
    """Return the aging bucket for a note: 'red', 'amber', or 'normal'.

    Red takes precedence over amber when both thresholds are crossed.
    """
    if days_open >= red_days:
        return "red"
    if days_open >= amber_days:
        return "amber"
    return "normal"


def _build_row(
    event: Any,
    ref_date: date,
    ref_tz: Any,
    amber_days: int,
    red_days: int,
) -> dict[str, Any]:
    """Assemble a single worklist row from a CurrentNoteStateEvent."""
    note = event.note
    patient = note.patient

    patient_name = (
        f"{patient.first_name} {patient.last_name}".strip()
        if patient
        else "Unknown Patient"
    )
    # Patient.id is the UUID used by the companion chart deep-link.
    patient_uuid = str(patient.id) if patient else ""

    note_type = note.note_type_version.name if note.note_type_version else ""
    note_title = (note.title or "").strip() or note_type or "Note"

    dos = note.datetime_of_service
    # Normalize the date of service into the provider's reference timezone so
    # the "days open" count lines up with the provider's local calendar.
    dos_local = dos.astimezone(ref_tz) if (dos and ref_tz) else dos
    dos_iso = dos.isoformat() if dos else None
    days_open = (ref_date - dos_local.date()).days if dos_local else 0
    # A negative count would mean a future date of service slipped through;
    # clamp to 0 so the UI never shows "-1 days open".
    if days_open < 0:
        days_open = 0

    return {
        "note_id": str(note.id),
        "patient_id": patient_uuid,
        "patient_name": patient_name,
        "note_title": note_title,
        "note_type": note_type,
        "date_of_service": dos_iso,
        "days_open": days_open,
        "aging": _aging_level(days_open, amber_days, red_days),
        "state": event.state,
        "state_label": _STATE_LABELS.get(event.state, str(event.state)),
    }
