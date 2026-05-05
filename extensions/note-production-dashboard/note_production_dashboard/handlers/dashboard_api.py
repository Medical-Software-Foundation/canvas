"""SimpleAPI handler for the note production dashboard.

Endpoints:
  GET /dashboard              — full-page HTML dashboard
  GET /providers              — JSON provider list with locked-note counts
  GET /providers/<id>/notes   — JSON note rows for a single provider
"""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.billing import BillingLineItem, BillingLineItemStatus
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates
from canvas_sdk.v1.data.staff import Staff
from django.db.models import Count, Prefetch


class _SettingsShim:
    """Stand-in for django.conf.settings — the plugin sandbox forbids that import.

    Tests monkeypatch the module-level ``settings`` name to inject a timezone.
    Production runs always see ``TIME_ZONE = "UTC"``. If per-instance localized
    times are needed later, swap this for a plugin secret read inside the
    handler (the helpers below already accept tz only via this shim).
    """

    TIME_ZONE = "UTC"


settings = _SettingsShim()

# Cache-bust token: generated once at module load so every deploy gets a fresh value.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

# ─── time-window helpers ──────────────────────────────────────────────────────


def _instance_tz() -> str:
    """Return the configured TIME_ZONE (falls back to UTC)."""
    return getattr(settings, "TIME_ZONE", "UTC")


def _window(period: str, week_start: str) -> tuple[datetime, datetime]:
    """Return (start, end) as UTC-aware datetimes for the requested period.

    All edges are calendar-aligned in the instance timezone.
    The right edge is the end-of-period (not 'now').
    """
    tz = _instance_tz()
    now = arrow.now(tz)

    if period == "monthly":
        start = now.floor("month")
        end = start.shift(months=1)
    elif period == "weekly":
        # arrow uses Monday=0 … Sunday=6 for weekday()
        # week_start='sunday' → anchor to most-recent Sunday
        # week_start='monday' → anchor to most-recent Monday
        anchor_weekday = 6 if week_start == "sunday" else 0  # arrow weekday ints
        days_back = (now.weekday() - anchor_weekday) % 7
        start = now.shift(days=-days_back).floor("day")
        end = start.shift(weeks=1)
    else:
        # daily (default)
        start = now.floor("day")
        end = start.shift(days=1)

    return start.datetime, end.datetime


# ─── data helpers ─────────────────────────────────────────────────────────────


def _format_dos(dt: datetime) -> str:
    """Format a datetime-of-service in the instance timezone."""
    tz = _instance_tz()
    local = arrow.get(dt).to(tz)
    return local.format("MM/DD HH:mm")


def _patient_display_name(patient: Any) -> str:
    """Format a Patient as 'Last, First'.

    Falls back gracefully when only one name is set, and returns "" if the
    patient is missing entirely.
    """
    if patient is None:
        return ""
    first = (getattr(patient, "first_name", "") or "").strip()
    last = (getattr(patient, "last_name", "") or "").strip()
    if last and first:
        return f"{last}, {first}"
    return last or first


def _provider_display_name(staff: Any) -> str:
    """Return 'First Last' or 'First Last, Credentials' for a Staff record."""
    name = f"{getattr(staff, 'first_name', '')} {getattr(staff, 'last_name', '')}".strip()
    # Staff.credentialed_name is a property that appends credentials if set;
    # fall back to plain name if credentials are not present.
    cred: str | None = getattr(staff, "credentialed_name", None)
    if cred and cred != name:
        return cred
    return name


def _rfv_text(note: Any) -> str:
    """Return the reason-for-visit text for the first RFV command on a note.

    Priority:
      1. Structured coding display / text
      2. Unstructured comment text
      3. Em-dash fallback
    """
    # note.commands is prefetched; filter client-side to avoid a DB round-trip.
    rfv_commands = [
        c for c in getattr(note, "commands", None).all()  # type: ignore[union-attr]
        if getattr(c, "schema_key", None) == "reasonForVisit"
    ]
    if not rfv_commands:
        return "—"

    # Sort by dbid ascending to get the earliest-added command.
    rfv_commands.sort(key=lambda c: getattr(c, "dbid", 0))
    data: dict[str, Any] = getattr(rfv_commands[0], "data", None) or {}

    coding: dict[str, Any] = (data.get("coding") or {})
    # Structured RFV has a 'text' key inside coding (display/text field).
    structured_text = str(coding.get("display") or coding.get("text") or "")
    if structured_text:
        return structured_text

    comment = str(data.get("comment") or "")
    if comment:
        return comment

    return "—"


_LOCKED_STATES = [NoteStates.LOCKED, NoteStates.RELOCKED, NoteStates.SIGNED]
"""States that count as 'locked' for the dashboard.

The enum members above hold the wire values "LKD", "RLK", "SGN".
Empirically, locking a note in Canvas auto-progresses LKD → SGN, so the
``CurrentNoteStateEvent.state`` for a locked note typically reads SGN, not LKD.
RELOCKED covers the relocked case.
"""


def _fetch_locked_state_events(start: datetime, end: datetime, provider_id: str | None = None):  # type: ignore[no-untyped-def]  # pragma: no cover
    """Return a queryset of CurrentNoteStateEvent for locked notes in [start, end).

    Uses select_related and prefetch_related to avoid N+1:
      - select_related: note__provider, note__patient, note__note_type_version
      - prefetch_related: note__billing_line_items (filtered to ACTIVE), note__commands

    Coverage: this function is patched in every endpoint test because it hits
    the ORM. The query construction is verified by integration smoke tests
    against a real database, not by unit tests.
    """
    qs = CurrentNoteStateEvent.objects.filter(
        state__in=_LOCKED_STATES,
        note__datetime_of_service__gte=start,
        note__datetime_of_service__lt=end,
    ).select_related(
        "note__provider",
        "note__patient",
        "note__note_type_version",
    ).prefetch_related(
        Prefetch(
            "note__billing_line_items",
            queryset=BillingLineItem.objects.filter(status=BillingLineItemStatus.ACTIVE),
            to_attr="active_billing_items",
        ),
        Prefetch(
            "note__commands",
            queryset=Command.objects.filter(schema_key="reasonForVisit").order_by("dbid"),
            to_attr="rfv_commands_prefetched",
        ),
    )

    if provider_id is not None:
        qs = qs.filter(note__provider__id=provider_id)

    return qs


def _build_provider_counts_result(
    counts_by_provider_id: dict[str, int],
    staff_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    """Combine aggregated counts with Staff records into the response shape.

    Pure function — extracted so the sort/tie-break/credentialed-name behavior
    can be unit-tested without mocking the ORM.
    """
    result: list[dict[str, Any]] = []
    for pid, count in counts_by_provider_id.items():
        staff = staff_by_id.get(pid)
        name = _provider_display_name(staff) if staff is not None else ""
        result.append({"provider_id": pid, "name": name, "count": count})
    result.sort(key=lambda x: (-x["count"], x["name"]))
    return result


def _fetch_provider_counts(start: datetime, end: datetime) -> list[dict[str, Any]]:  # pragma: no cover
    """Return [{provider_id, name, count}, ...] for locked notes in [start, end).

    Uses a SQL GROUP BY to count notes per provider, then a single follow-up
    query to load the Staff records so credentialed names can be resolved
    (credentialed_name is a Python @cached_property and cannot be pulled via
    .values()). Two queries total, regardless of note count.

    Coverage: this function is patched in every endpoint test because it hits
    the ORM. The pure result-shaping logic is exercised through
    _build_provider_counts_result, which has its own dedicated unit tests.
    """
    # Note: Staff.id is a CharField (db_column="key"); the FK column on Note
    # (provider_id) actually references Staff.dbid (the BigAutoField PK), so
    # we must traverse the relation with note__provider__id to retrieve the
    # human-facing string id used everywhere else in the dashboard.
    aggregated = (
        CurrentNoteStateEvent.objects.filter(
            state__in=_LOCKED_STATES,
            note__datetime_of_service__gte=start,
            note__datetime_of_service__lt=end,
            note__provider__isnull=False,
        )
        .values("note__provider__id")
        .annotate(count=Count("id"))
    )

    counts_by_provider_id: dict[str, int] = {}
    for row in aggregated:
        counts_by_provider_id[str(row["note__provider__id"])] = row["count"]

    if not counts_by_provider_id:
        return []

    staff_qs = Staff.objects.filter(id__in=list(counts_by_provider_id.keys())).prefetch_related("roles")
    staff_by_id = {str(s.id): s for s in staff_qs}

    return _build_provider_counts_result(counts_by_provider_id, staff_by_id)


# ─── SimpleAPI ────────────────────────────────────────────────────────────────


class NoteProductionDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    """HTTP endpoints backing the note production dashboard."""

    @api.get("/dashboard")
    def dashboard_page(self) -> list[Response | Effect]:
        """Return the single-page dashboard HTML."""
        period = self.request.query_params.get("period", "daily")
        week_start = self.request.query_params.get("week_start", "sunday")
        # Validate inputs server-side; unknown values fall back to defaults.
        if period not in ("daily", "weekly", "monthly"):
            period = "daily"
        if week_start not in ("sunday", "monday"):
            week_start = "sunday"
        html = render_to_string(
            "static/dashboard.html",
            {"period": period, "week_start": week_start, "cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        """Serve the dashboard JavaScript as a static asset."""
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        """Serve the dashboard CSS as a static asset."""
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/providers")
    def providers_list(self) -> list[Response | Effect]:
        """Return [{provider_id, name, count}] sorted by count desc, then name."""
        period = self.request.query_params.get("period", "daily")
        week_start = self.request.query_params.get("week_start", "sunday")
        if period not in ("daily", "weekly", "monthly"):
            period = "daily"
        if week_start not in ("sunday", "monday"):
            week_start = "sunday"

        start, end = _window(period, week_start)
        result = _fetch_provider_counts(start, end)
        return [JSONResponse(result, status_code=HTTPStatus.OK)]

    @api.get("/providers/<provider_id>/notes")
    def provider_notes(self) -> list[Response | Effect]:
        """Return note rows for a single provider in the requested period."""
        provider_id = self.request.path_params["provider_id"]
        period = self.request.query_params.get("period", "daily")
        week_start = self.request.query_params.get("week_start", "sunday")
        if period not in ("daily", "weekly", "monthly"):
            period = "daily"
        if week_start not in ("sunday", "monday"):
            week_start = "sunday"

        start, end = _window(period, week_start)

        events = _fetch_locked_state_events(start, end, provider_id=provider_id)

        rows = []
        for event in events:
            note = event.note
            patient = note.patient
            patient_name = _patient_display_name(patient)

            # CPT codes from prefetched active billing items.
            active_items = getattr(note, "active_billing_items", [])
            cpts = ", ".join(item.cpt for item in active_items if item.cpt)

            # Note type name.
            note_type = (
                note.note_type_version.name if note.note_type_version else ""
            )

            # RFV: use prefetched commands.
            rfv_commands = getattr(note, "rfv_commands_prefetched", [])
            if rfv_commands:
                data = rfv_commands[0].data or {}
                coding = data.get("coding") or {}
                rfv = (
                    coding.get("display")
                    or coding.get("text")
                    or data.get("comment")
                    or "—"
                )
            else:
                rfv = "—"

            dt = note.datetime_of_service
            rows.append({
                "note_id": str(note.id),
                "patient": patient_name,
                "datetime_of_service": _format_dos(dt),
                "sort_dt": dt.isoformat() if dt else "",
                "cpt": cpts,
                "note_type": note_type,
                "rfv": rfv,
            })

        # Server-side default: datetime descending. The client may resort by
        # patient or datetime in either direction without a refetch.
        rows.sort(key=lambda r: r["sort_dt"], reverse=True)

        return [JSONResponse(rows, status_code=HTTPStatus.OK)]
