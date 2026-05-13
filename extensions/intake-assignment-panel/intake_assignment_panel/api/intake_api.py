from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus

import arrow
from django.db.models import Prefetch, Q

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.common import AddressState, AddressUse
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.patient import PatientAddress
from canvas_sdk.v1.data.staff import Staff, StaffLicense


PENDING_NOTE_STATES = [
    NoteStates.NEW,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]


def get_licensed_states(staff_id: str, today: date) -> set[str] | None:
    """Return the set of active state-license codes for a staff member.

    Returns None when the staff has zero active state licenses on file,
    signaling "show everything, unfiltered".
    """
    state_codes = set(
        StaffLicense.objects.filter(
            staff__id=staff_id,
            license_type=StaffLicense.LicenseType.STATE_LICENSE,
            expiration_date__gte=today,
            state__isnull=False,
        )
        .exclude(state="")
        .values_list("state", flat=True)
    )
    return state_codes or None


def filter_rows_by_licensed_states(
    rows: list[dict], licensed_states: set[str] | None
) -> list[dict]:
    """Filter rows by licensed states. None = no filter applied."""
    if licensed_states is None:
        return rows
    return [r for r in rows if r["state"] and r["state"] in licensed_states]


def sort_rows(rows: list[dict], sort_by: str, sort_dir: str) -> list[dict]:
    """Sort rows by column. Defaults to oldest-pending-first."""
    reverse = sort_dir == "desc"
    if sort_by == "patient":
        return sorted(rows, key=lambda r: (r["patient_name"] or "").lower(), reverse=reverse)
    if sort_by == "state":
        return sorted(rows, key=lambda r: r["state"] or "", reverse=reverse)
    if sort_by == "time_pending":
        # Larger time_pending = older note. desc = oldest first.
        return sorted(rows, key=lambda r: r["time_pending_seconds"], reverse=reverse)
    # Default: oldest pending first (largest time_pending first)
    return sorted(rows, key=lambda r: r["time_pending_seconds"], reverse=True)


def humanize_pending(delta: timedelta) -> str:
    """Render a timedelta like '3d 7h', '2h 14m', '5m'."""
    total_seconds = int(max(delta.total_seconds(), 0))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class IntakeAPI(StaffSessionAuthMixin, SimpleAPI):
    """API for the Intake Assignment Panel application."""

    BASE_PATH = "/plugin-io/api/intake_assignment_panel"
    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        context = self._shell_context()
        return [
            HTMLResponse(
                render_to_string("static/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/scripts.js")
    def get_scripts(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/scripts.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/table")
    def get_table(self) -> list[Response | Effect]:
        sort_by = self.request.query_params.get("sort_by", "").strip()
        sort_dir = self.request.query_params.get("sort_dir", "").strip() or "desc"

        staff_id = self.request.headers["canvas-logged-in-user-id"]
        today = arrow.utcnow().date()
        licensed_states = get_licensed_states(staff_id, today)

        rows = self._build_pending_intake_rows()
        rows = filter_rows_by_licensed_states(rows, licensed_states)
        rows = sort_rows(rows, sort_by, sort_dir)

        context = {
            "rows": rows,
            "has_license_filter": licensed_states is not None,
            "licensed_states": sorted(licensed_states) if licensed_states else [],
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "total_count": len(rows),
        }
        return [
            HTMLResponse(
                render_to_string("static/table.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    def _shell_context(self) -> dict:
        staff = Staff.objects.values("first_name", "last_name").get(
            id=self.request.headers["canvas-logged-in-user-id"]
        )
        return {
            "first_name": staff["first_name"],
            "last_name": staff["last_name"],
        }

    def _intake_note_types(self) -> list[str]:
        raw = self.secrets.get("INTAKE_NOTE_TYPES") or ""
        return [n.strip() for n in raw.strip().strip('"\'').split(",") if n.strip()]

    def _instance_url(self) -> str:
        raw = self.secrets.get("CANVAS_INSTANCE_URL") or ""
        return raw.strip().strip('"\'').rstrip("/")

    def _build_pending_intake_rows(self) -> list[dict]:
        note_type_names = self._intake_note_types()
        if not note_type_names:
            return []

        instance_url = self._instance_url()

        home_addresses_qs = PatientAddress.objects.filter(
            use=AddressUse.HOME,
            state=AddressState.ACTIVE,
        ).order_by("-start")

        name_q = Q()
        for name in note_type_names:
            name_q |= Q(note_type_version__name__iexact=name)

        notes = (
            Note.objects.filter(
                name_q,
                current_state__state__in=PENDING_NOTE_STATES,
                patient__isnull=False,
            )
            .select_related("patient")
            .prefetch_related(
                Prefetch("patient__addresses", queryset=home_addresses_qs, to_attr="home_addresses_cache")
            )
        )

        now = datetime.now(timezone.utc)
        rows: list[dict] = []
        for note in notes:
            patient = note.patient
            if patient is None:
                continue

            home = next(iter(getattr(patient, "home_addresses_cache", []) or []), None)
            state_code = (home.state_code or "").strip().upper() if home and home.state_code else ""

            created_at = note.created
            if not isinstance(created_at, datetime):
                created_at = arrow.get(created_at).datetime
            delta = now - created_at

            note_path = f"/patient/{patient.id}#noteId={note.dbid}"
            note_url = f"{instance_url}{note_path}" if instance_url else note_path

            rows.append({
                "patient_id": str(patient.id),
                "patient_name": f"{patient.first_name or ''} {patient.last_name or ''}".strip(),
                "state": state_code or None,
                "time_pending_seconds": max(int(delta.total_seconds()), 0),
                "time_pending_display": humanize_pending(delta),
                "note_url": note_url,
                "note_dbid": note.dbid,
            })

        return rows
