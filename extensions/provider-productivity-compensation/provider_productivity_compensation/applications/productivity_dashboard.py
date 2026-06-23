import base64
import json
from http import HTTPStatus

import arrow
from django.db.models import Count

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.simple_api import Response, JSONResponse
from canvas_sdk.handlers.application import Application
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note, NoteStates, CurrentNoteStateEvent
from canvas_sdk.v1.data.billing import BillingLineItem, BillingLineItemStatus
from canvas_sdk.v1.data.staff import Staff

try:
    # Used to build Canvas permalink URNs. Allowed on newer plugin runtimes;
    # on older ones the import is sandbox-blocked, so we degrade gracefully.
    from canvas_sdk.v1.data.django_content_type import ContentType
except ImportError:  # pragma: no cover - depends on runtime SDK version
    ContentType = None


SIGNED_STATES = [NoteStates.LOCKED, NoteStates.RELOCKED, "SGN"]
OPEN_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]
VISIBLE_STATES = SIGNED_STATES + OPEN_STATES


def _get_pay_period(ref) -> tuple:  # type: ignore[no-untyped-def]
    """Return (start, end) for the pay period containing the given date.

    Pay periods are 1st-15th and 16th-end of month.
    """
    if ref.day <= 15:
        start = ref.replace(day=1).floor("day")
        end = ref.replace(day=15).ceil("day")
    else:
        start = ref.replace(day=16).floor("day")
        end = ref.ceil("month")
    return start, end


def _get_date_range(period: str, start_date: str | None = None, end_date: str | None = None, tz: str | None = None) -> tuple:
    """Return (start_date, end_date) for the given period in the given timezone."""
    try:
        now = arrow.now(tz) if tz else arrow.now()
    except Exception:
        now = arrow.now()  # invalid tz string -> fall back to server default
    if period == "custom" and start_date and end_date:
        try:
            user_tz = tz or "UTC"
            start = arrow.get(start_date).replace(tzinfo=user_tz).floor("day")
            end = arrow.get(end_date).replace(tzinfo=user_tz).ceil("day")
            return start.datetime, end.datetime
        except (ValueError, arrow.parser.ParserError, Exception):
            pass  # fall through to default
    if period == "this_pay_period":
        start, end = _get_pay_period(now)
        return start.datetime, end.datetime
    if period == "last_pay_period":
        # Shift into the previous pay period
        current_start, _ = _get_pay_period(now)
        prev_day = current_start.shift(days=-1)
        start, end = _get_pay_period(prev_day)
        return start.datetime, end.datetime
    if period == "week":
        start = now.floor("week")  # Monday
    elif period == "month":
        start = now.floor("month")  # 1st of month
    else:
        start = now.floor("day")   # today
    end = now.ceil("day")
    return start.datetime, end.datetime


class ProductivityDashboardApplication(Application):
    """Launches the Provider Productivity Dashboard modal."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            content=render_to_string("templates/dashboard.html"),
            target=LaunchModalEffect.TargetType.PAGE,
            title="Provider Productivity Dashboard",
        ).apply()


class ProductivityDashboardApi(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for the Provider Productivity Dashboard."""

    def _is_compensation_superuser(self) -> bool:
        """Check if the logged-in user's staff ID is in COMPENSATION_SUPERUSER_IDS.

        Superusers may view compensation for any provider; everyone else may only
        see compensation for their own data.
        """
        superuser_ids_raw = self.secrets.get("COMPENSATION_SUPERUSER_IDS", "")
        if not superuser_ids_raw:
            return False
        superuser_ids = [sid.strip() for sid in superuser_ids_raw.split(",") if sid.strip()]
        staff_id: str = self.request.headers["canvas-logged-in-user-id"]
        return staff_id in superuser_ids

    def _resolve_staff_id(self) -> str:
        """Return the provider ID to query for.

        Anyone may view any provider's metrics; an explicit provider_id wins,
        otherwise we default to the logged-in user.
        """
        logged_in: str = self.request.headers["canvas-logged-in-user-id"]
        requested: str = self.request.query_params.get("provider_id", "")
        return str(requested) if requested else str(logged_in)

    def _get_visible_note_ids(self, staff_id: str, start, end) -> list:  # type: ignore[no-untyped-def]
        """Return visible note IDs for a single provider in the given range."""
        filters = {
            "state__in": VISIBLE_STATES,
            "note__datetime_of_service__gte": start,
            "note__datetime_of_service__lte": end,
            "note__note_type_version__is_billable": True,
            "note__provider__id": staff_id,
        }
        return list(
            CurrentNoteStateEvent.objects.filter(**filters)
            .values_list("note_id", flat=True)
        )

    def _base_url(self) -> str:
        """Absolute origin of the current request, used to build permalinks."""
        headers = self.request.headers
        host = headers.get("x-forwarded-host") or headers.get("host") or ""
        proto = headers.get("x-forwarded-proto") or "https"
        return f"{proto}://{host}" if host else ""

    def _note_permalink(self, note) -> str:  # type: ignore[no-untyped-def]
        """Deep link to a specific note.

        Prefers Canvas's permalink URN — a base64-encoded
        "Note:<content_type_id>:<note_pk>" under /permalinks/v1/ — which Canvas
        resolves and redirects to the correct chart/note UI state. When the
        ContentType model is unavailable (older plugin runtime), falls back to
        the chart URL with a noteId query param, which is the very target the
        permalink resolver redirects to.
        """
        base = self._base_url()
        if not hasattr(self, "_note_ct_id"):
            ct = (
                ContentType.objects.filter(app_label="api", model="note").first()
                if ContentType is not None
                else None
            )
            self._note_ct_id: int | None = ct.dbid if ct else None
        if self._note_ct_id:
            token = base64.b64encode(
                f"Note:{self._note_ct_id}:{note.dbid}".encode("ascii")
            ).decode("ascii")
            return f"{base}/permalinks/v1/{token}"
        return f"{base}/patient/{note.patient.id}?noteId={note.id}"

    def _get_fee_schedule(self, staff_id: str) -> dict[str, float] | None:
        """Return the fee schedule rates for a provider, or None if unavailable.

        The PROVIDER_FEE_SCHEDULE_MAP secret is keyed by credentialed_name
        (e.g. "Melissa Walsh NP"), so we resolve staff_id -> name first.
        """
        try:
            map_raw = self.secrets.get("PROVIDER_FEE_SCHEDULE_MAP", "")
            if not map_raw:
                return None
            if not hasattr(self, "_parsed_map"):
                self._parsed_map: dict[str, str] = json.loads(map_raw)

            # Resolve staff_id to credentialed_name via the Staff model
            # credentialed_name is a property, not a DB field, so we fetch the object
            if not hasattr(self, "_staff_name_cache"):
                self._staff_name_cache: dict[str, str | None] = {}
            if staff_id not in self._staff_name_cache:
                staff_obj = Staff.objects.filter(id=staff_id).first()
                self._staff_name_cache[staff_id] = staff_obj.credentialed_name if staff_obj else None
            staff_name = self._staff_name_cache[staff_id]
            if not staff_name:
                return None

            plan_key = self._parsed_map.get(staff_name)
            if not plan_key:
                return None

            rates_raw = self.secrets.get("FEE_SCHEDULE_RATES", "")
            if not rates_raw:
                return None
            if not hasattr(self, "_parsed_rates"):
                self._parsed_rates: dict[str, dict[str, float]] = json.loads(rates_raw)
            schedule = self._parsed_rates.get(plan_key)
            return schedule if schedule else None
        except (json.JSONDecodeError, TypeError, AttributeError):
            return None

    def _should_show_earnings(self, staff_id: str) -> bool:
        """Return True only when the viewer may see this provider's compensation.

        Compensation is private to the logged-in user, except for listed
        superusers who may see it for any provider. A fee schedule must exist.
        """
        logged_in: str = self.request.headers["canvas-logged-in-user-id"]
        if staff_id == logged_in:
            return self._get_fee_schedule(staff_id) is not None
        if self._is_compensation_superuser():
            return self._get_fee_schedule(staff_id) is not None
        return False

    def _compute_earnings(self, cpt_codes: list[str], fee_schedule: dict[str, float]) -> float:
        """Sum the fee schedule rates for a list of CPT codes."""
        return round(sum(fee_schedule.get(cpt, 0.0) for cpt in cpt_codes), 2)

    @api.get("/api/providers")
    def get_providers(self) -> list[Response | Effect]:
        """Return the list of active providers. Available to all users."""
        logged_in = self.request.headers["canvas-logged-in-user-id"]

        # prefetch_related("roles") avoids an N+1: credentialed_name resolves the
        # provider's top clinical role via self.roles.all(), which would otherwise
        # fire one query per active staff member.
        providers = [
            {"id": str(s.id), "name": s.credentialed_name}
            for s in Staff.objects.filter(active=True)
            .prefetch_related("roles")
            .order_by("first_name", "last_name")
        ]

        return [JSONResponse({
            "logged_in_staff_id": logged_in,
            "providers": providers,
        }, status_code=HTTPStatus.OK)]

    @api.get("/api/metrics")
    def get_metrics(self) -> list[Response | Effect]:
        """Return summary metrics for patients seen, CPT codes, and note status."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        tz = self.request.query_params.get("tz", "") or None
        start, end = _get_date_range(period, self.request.query_params.get("start_date"), self.request.query_params.get("end_date"), tz=tz)

        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)

        # Encounters — total notes (not distinct patients)
        encounters = len(visible_note_ids)

        # CPT codes — via BillingLineItem linked to visible notes
        billing_items = (
            BillingLineItem.objects.filter(
                note__dbid__in=visible_note_ids,
                status=BillingLineItemStatus.ACTIVE,
            )
            .values("cpt", "description")
            .annotate(count=Count("id"))
            .order_by("-count", "cpt")
        )

        # Earnings
        show_earnings = self._should_show_earnings(staff_id)
        fee_schedule = self._get_fee_schedule(staff_id) if show_earnings else None

        cpt_codes = []
        for item in billing_items:
            earned = round(fee_schedule.get(item["cpt"], 0.0) * item["count"], 2) if fee_schedule else 0.0
            cpt_codes.append({
                "cpt": item["cpt"],
                "description": item["description"],
                "count": item["count"],
                "amount_earned": earned,
            })
        cpt_total = sum(item["count"] for item in cpt_codes)
        amount_earned = round(sum(item["amount_earned"] for item in cpt_codes), 2)

        # Note signing status
        signed_count = CurrentNoteStateEvent.objects.filter(
            note_id__in=visible_note_ids,
            state__in=SIGNED_STATES,
        ).count()
        open_count = CurrentNoteStateEvent.objects.filter(
            note_id__in=visible_note_ids,
            state__in=OPEN_STATES,
        ).count()

        return [JSONResponse({
            "period": period,
            "encounters": encounters,
            "cpt_total": cpt_total,
            "cpt_codes": cpt_codes,
            "notes_signed": signed_count,
            "notes_open": open_count,
            "notes_total": signed_count + open_count,
            "show_earnings": show_earnings,
            "amount_earned": amount_earned,
        }, status_code=HTTPStatus.OK)]

    @api.get("/api/patients")
    def get_patients(self) -> list[Response | Effect]:
        """Return note-level rows with patient, DOS, CPTs, and note status."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        tz = self.request.query_params.get("tz", "") or None
        start, end = _get_date_range(period, self.request.query_params.get("start_date"), self.request.query_params.get("end_date"), tz=tz)

        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)

        show_earnings = self._should_show_earnings(staff_id)
        fee_schedule = self._get_fee_schedule(staff_id) if show_earnings else None

        notes = (
            Note.objects.filter(dbid__in=visible_note_ids)
            .select_related("patient")
            .order_by("-datetime_of_service")
        )

        state_map = {}
        for note_id, state in CurrentNoteStateEvent.objects.filter(
            note_id__in=visible_note_ids
        ).values_list("note_id", "state"):
            state_map[note_id] = state

        cpt_map: dict[int, list[str]] = {}
        for item in BillingLineItem.objects.filter(
            note__dbid__in=visible_note_ids, status=BillingLineItemStatus.ACTIVE
        ).values_list("note__dbid", "cpt"):
            cpt_map.setdefault(item[0], []).append(item[1])

        rows = []
        for note in notes:
            patient = note.patient
            if not patient:
                continue
            full_name = (
                f"{patient.first_name} ({patient.nickname}) {patient.last_name}"
                if patient.nickname
                else f"{patient.first_name} {patient.last_name}"
            )

            cpts = cpt_map.get(note.dbid, [])

            state = state_map.get(note.dbid)
            status = "Signed" if state in SIGNED_STATES else "Open"

            dos = arrow.get(note.datetime_of_service).isoformat() if note.datetime_of_service else None

            earned = self._compute_earnings(cpts, fee_schedule) if fee_schedule else 0.0

            rows.append({
                "patient_name": full_name or "Unknown",
                "patient_id": str(patient.id),
                # Permalink that deep-links to this specific note
                "chart_link": self._note_permalink(note),
                "dos": dos,
                "cpts": cpts,
                "status": status,
                "amount_earned": earned,
            })

        return [JSONResponse({"period": period, "notes": rows, "show_earnings": show_earnings}, status_code=HTTPStatus.OK)]

    @api.get("/api/cpt-patients")
    def get_cpt_patients(self) -> list[Response | Effect]:
        """Return patients and DOS for a specific CPT code."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        cpt = self.request.query_params.get("cpt", "")
        tz = self.request.query_params.get("tz", "") or None
        start, end = _get_date_range(period, self.request.query_params.get("start_date"), self.request.query_params.get("end_date"), tz=tz)

        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)

        show_earnings = self._should_show_earnings(staff_id)
        fee_schedule = self._get_fee_schedule(staff_id) if show_earnings else None
        rate = fee_schedule.get(cpt, 0.0) if fee_schedule else 0.0

        billing_items = (
            BillingLineItem.objects.filter(
                note__dbid__in=visible_note_ids,
                status=BillingLineItemStatus.ACTIVE,
                cpt=cpt,
            )
            .select_related("note__patient")
            .order_by("-note__datetime_of_service")
        )

        rows = []
        for item in billing_items:
            patient = item.note.patient if item.note else None
            if not patient:
                continue
            full_name = (
                f"{patient.first_name} ({patient.nickname}) {patient.last_name}"
                if patient.nickname
                else f"{patient.first_name} {patient.last_name}"
            )
            dos = arrow.get(item.note.datetime_of_service).isoformat() if item.note.datetime_of_service else None
            rows.append({
                "patient_name": full_name or "Unknown",
                "patient_id": str(patient.id),
                # Permalink that deep-links to this specific note
                "chart_link": self._note_permalink(item.note),
                "dos": dos,
                "amount_earned": rate,
            })

        return [JSONResponse({"period": period, "cpt": cpt, "patients": rows, "show_earnings": show_earnings}, status_code=HTTPStatus.OK)]
