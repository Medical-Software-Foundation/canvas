from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any

import arrow
from django.db.models import Count, Max

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.simple_api import Response, JSONResponse
from canvas_sdk.handlers.application import Application
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note, NoteStates, NoteTypeCategories, CurrentNoteStateEvent, NoteStateChangeEvent
from canvas_sdk.v1.data.billing import BillingLineItem, BillingLineItemStatus
from canvas_sdk.v1.data.imaging import ImagingOrder
from canvas_sdk.v1.data.lab import LabOrder
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.protocol_current import ProtocolCurrent
from canvas_sdk.v1.data.protocol_result import ProtocolResultStatus
from canvas_sdk.v1.data.referral import Referral
from canvas_sdk.v1.data.staff import Staff


SIGNED_STATES = [NoteStates.LOCKED, NoteStates.RELOCKED, NoteStates.SIGNED]
OPEN_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]
VISIBLE_STATES = SIGNED_STATES + OPEN_STATES
EXCLUDED_CATEGORIES = [NoteTypeCategories.MESSAGE, NoteTypeCategories.LETTER]
DME_KEYWORDS = [
    "dme", "durable medical equipment", "equipment", "supply", "brace",
    "wheelchair", "cpap", "nebulizer", "walker", "oxygen", "prosthetic",
    "orthotic", "crutch", "splint", "catheter",
]


def _get_date_range(period: str) -> tuple:
    """Return (start_date, end_date) for the given period."""
    now = arrow.now()
    if period == "week":
        start = now.floor("week")  # Monday
    elif period == "month":
        start = now.floor("month")  # 1st of month
    elif period == "quarter":
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(month=quarter_month, day=1).floor("day")
    elif period == "year":
        start = now.replace(month=1, day=1).floor("day")
    else:
        start = now.floor("day")   # today
    end = now.ceil("day")
    return start.datetime, end.datetime


def _is_dme_referral(notes_text: str) -> bool:
    """Check if a referral's notes field contains DME-related keywords."""
    lower = (notes_text or "").lower()
    return any(kw in lower for kw in DME_KEYWORDS)


def _format_duration(delta: "timedelta") -> str:
    """Format a timedelta as a human-readable string like '3d 4h' or '45m'."""
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "0m"
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class ProductivityDashboardApplication(Application):
    """Launches the Panel Management Dashboard modal."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            content=render_to_string("templates/dashboard.html"),
            target=LaunchModalEffect.TargetType.PAGE,
            title="Panel Management Dashboard",
        ).apply()


class ProductivityDashboardApi(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for the Provider Productivity Dashboard."""

    def _resolve_staff_id(self) -> str:
        """Return the provider ID to query for. Any user may pass 'all' or a specific ID."""
        logged_in: str = self.request.headers["canvas-logged-in-user-id"]
        requested: str = self.request.query_params.get("provider_id", "")
        if requested:
            return str(requested)
        return str(logged_in)

    def _get_visible_note_ids(self, staff_id: str, start: datetime, end: datetime) -> list[int]:
        """Return visible note IDs, optionally filtered to a single provider."""
        filters = {
            "state__in": VISIBLE_STATES,
            "note__datetime_of_service__gte": start,
            "note__datetime_of_service__lte": end,
        }
        if staff_id != "all":
            filters["note__provider__id"] = staff_id
        return list(
            CurrentNoteStateEvent.objects.filter(**filters)
            .exclude(note__note_type_version__category__in=EXCLUDED_CATEGORIES)
            .values_list("note_id", flat=True)
        )

    @api.get("/api/providers")
    def get_providers(self) -> list[Response | Effect]:
        """Return provider list for all users."""
        logged_in = self.request.headers["canvas-logged-in-user-id"]

        providers = [
            {"id": str(s.id), "name": s.credentialed_name}
            for s in Staff.objects.filter(active=True).order_by("first_name", "last_name")
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
        start, end = _get_date_range(period)

        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)

        base_notes = Note.objects.filter(dbid__in=visible_note_ids)

        # Patients seen — distinct patients (exclude notes with no patient so a
        # null patient_id is not counted as its own "patient")
        patients_seen = (
            base_notes.exclude(patient__isnull=True)
            .values("patient__id")
            .distinct()
            .count()
        )

        # CPT codes — via BillingLineItem linked to visible notes
        billing_items = (
            BillingLineItem.objects.filter(
                note__dbid__in=visible_note_ids,
                status=BillingLineItemStatus.ACTIVE,
            )
            .values("cpt")
            # Max() so a real description wins over an empty string for codes whose
            # line items carry mixed (some blank) descriptions; Min would surface "".
            .annotate(count=Count("id"), description=Max("description"))
            .order_by("-count", "cpt")
        )

        cpt_codes = [
            {"cpt": item["cpt"], "description": item["description"], "count": item["count"]}
            for item in billing_items
        ]
        cpt_total = sum(item["count"] for item in cpt_codes)

        # Care gaps — scoped to patients seen in the period. The same scoping is
        # applied for a single provider and for "All Providers", so both the open
        # and closed counts track the selected time window rather than silently
        # falling back to a practice-wide, period-independent total.
        patient_ids = list(
            base_notes.exclude(patient__isnull=True)
            .values_list("patient__id", flat=True)
            .distinct()
        )
        care_gaps_open = ProtocolCurrent.objects.filter(
            status=ProtocolResultStatus.STATUS_DUE,
            patient__id__in=patient_ids,
        ).count()
        care_gaps_closed = ProtocolCurrent.objects.filter(
            status=ProtocolResultStatus.STATUS_SATISFIED,
            modified__gte=start,
            modified__lte=end,
            patient__id__in=patient_ids,
        ).count()

        # Note signing status
        signed_count = CurrentNoteStateEvent.objects.filter(
            note_id__in=visible_note_ids,
            state__in=SIGNED_STATES,
        ).count()
        open_count = CurrentNoteStateEvent.objects.filter(
            note_id__in=visible_note_ids,
            state__in=OPEN_STATES,
        ).count()

        # Average time to close — for signed notes, find the first signing event
        avg_time_to_close = "—"
        if visible_note_ids:
            sign_events = (
                NoteStateChangeEvent.objects.filter(
                    note_id__in=visible_note_ids,
                    state__in=SIGNED_STATES,
                )
                .select_related("note")
                .order_by("note_id", "created")
            )
            # Build map of note_id -> first sign event created time
            first_sign = {}
            for evt in sign_events:
                if evt.note_id not in first_sign:
                    first_sign[evt.note_id] = evt.created
            # Compute durations
            durations = []
            for note in base_notes:
                if note.dbid in first_sign and note.created:
                    delta = first_sign[note.dbid] - note.created
                    if delta.total_seconds() >= 0:
                        durations.append(delta)
            if durations:
                avg_seconds = sum(d.total_seconds() for d in durations) / len(durations)
                avg_time_to_close = _format_duration(timedelta(seconds=avg_seconds))

        return [JSONResponse({
            "period": period,
            "patients_seen": patients_seen,
            "cpt_total": cpt_total,
            "cpt_codes": cpt_codes,
            "notes_signed": signed_count,
            "notes_open": open_count,
            "notes_total": signed_count + open_count,
            "unsigned_notes": open_count,
            "care_gaps_open": care_gaps_open,
            "care_gaps_closed": care_gaps_closed,
            "avg_time_to_close": avg_time_to_close,
        }, status_code=HTTPStatus.OK)]

    @api.get("/api/patients")
    def get_patients(self) -> list[Response | Effect]:
        """Return note-level rows with patient, DOS, CPTs, and note status."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        start, end = _get_date_range(period)

        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)

        notes = (
            Note.objects.filter(dbid__in=visible_note_ids)
            .select_related("patient")
            .order_by("-datetime_of_service")
        )

        state_map = {}
        for state_event in CurrentNoteStateEvent.objects.filter(note_id__in=visible_note_ids):
            state_map[state_event.note_id] = state_event.state

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

            dos = arrow.get(note.datetime_of_service).format("MMM DD, YYYY h:mm A") if note.datetime_of_service else "Unknown"

            rows.append({
                "patient_name": full_name or "Unknown",
                "patient_id": str(patient.id),
                "chart_link": f"/patient/{patient.id}",
                "dos": dos,
                "cpts": cpts,
                "status": status,
            })

        return [JSONResponse({"period": period, "notes": rows}, status_code=HTTPStatus.OK)]

    @api.get("/api/cpt-patients")
    def get_cpt_patients(self) -> list[Response | Effect]:
        """Return patients and DOS for a specific CPT code."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        cpt = self.request.query_params.get("cpt", "")
        start, end = _get_date_range(period)

        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)

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
            dos = arrow.get(item.note.datetime_of_service).format("MMM DD, YYYY h:mm A") if item.note.datetime_of_service else "Unknown"
            rows.append({
                "patient_name": full_name or "Unknown",
                "patient_id": str(patient.id),
                # Link straight to the note that captured this CPT code. Canvas opens
                # a note via the chart fragment #noteId=<dbid> (integer dbid).
                "chart_link": f"/patient/{patient.id}#noteId={item.note.dbid}",
                "dos": dos,
            })

        return [JSONResponse({"period": period, "cpt": cpt, "patients": rows}, status_code=HTTPStatus.OK)]

    @api.get("/api/unsigned-notes")
    def get_unsigned_notes(self) -> list[Response | Effect]:
        """Return unsigned notes sorted by longest open first."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        start, end = _get_date_range(period)

        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)

        # Filter to only open (unsigned) notes
        open_note_ids = list(
            CurrentNoteStateEvent.objects.filter(
                note_id__in=visible_note_ids,
                state__in=OPEN_STATES,
            ).values_list("note_id", flat=True)
        )

        notes = (
            Note.objects.filter(dbid__in=open_note_ids)
            .select_related("patient", "provider")
            .order_by("created")  # oldest first = longest open first
        )

        now = arrow.now().datetime
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
            provider_name = note.provider.credentialed_name if note.provider else "Unknown"
            note_date = (
                arrow.get(note.datetime_of_service).format("MMM DD, YYYY h:mm A")
                if note.datetime_of_service
                else "Unknown"
            )
            time_open = _format_duration(now - note.created) if note.created else "Unknown"

            rows.append({
                "patient_name": full_name or "Unknown",
                "patient_id": str(patient.id),
                # Link straight to the unsigned note via the chart fragment #noteId=<dbid>.
                "chart_link": f"/patient/{patient.id}#noteId={note.dbid}",
                "note_date": note_date,
                "provider_name": provider_name,
                "time_open": time_open,
            })

        return [JSONResponse({
            "period": period,
            "count": len(rows),
            "notes": rows,
        }, status_code=HTTPStatus.OK)]

    @api.get("/api/care-gaps-closed")
    def get_care_gaps_closed(self) -> list[Response | Effect]:
        """Return care gaps closed (satisfied protocols) within the period."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        start, end = _get_date_range(period)

        # Scope to patients seen in the period for both single-provider and
        # "All Providers" mode, so this detail list matches the care-gaps-closed
        # count on the summary card.
        visible_note_ids = self._get_visible_note_ids(staff_id, start, end)
        patient_ids = list(
            Note.objects.filter(dbid__in=visible_note_ids)
            .exclude(patient__isnull=True)
            .values_list("patient__id", flat=True)
            .distinct()
        )
        filters = {
            "status": ProtocolResultStatus.STATUS_SATISFIED,
            "modified__gte": start,
            "modified__lte": end,
            "patient__id__in": patient_ids,
        }

        protocols = (
            ProtocolCurrent.objects.filter(**filters)
            .select_related("patient")
            .order_by("-modified")
        )

        rows = []
        for protocol in protocols:
            patient = protocol.patient
            if not patient:
                continue
            full_name = (
                f"{patient.first_name} ({patient.nickname}) {patient.last_name}"
                if patient.nickname
                else f"{patient.first_name} {patient.last_name}"
            )
            date_resolved = (
                arrow.get(protocol.modified).format("MMM DD, YYYY")
                if protocol.modified
                else "Unknown"
            )
            rows.append({
                "patient_name": full_name or "Unknown",
                "patient_id": str(patient.id),
                "chart_link": f"/patient/{patient.id}",
                "protocol_title": protocol.title or "Untitled",
                "date_resolved": date_resolved,
            })

        return [JSONResponse({
            "period": period,
            "count": len(rows),
            "gaps": rows,
        }, status_code=HTTPStatus.OK)]

    @api.get("/api/orders")
    def get_orders(self) -> list[Response | Effect]:
        """Return orders (labs, imaging, referrals, DME) within the period."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        order_type = self.request.query_params.get("order_type", "all")
        start, end = _get_date_range(period)

        rows = []

        def _patient_name(patient: Any) -> str:
            if patient.nickname:
                return f"{patient.first_name} ({patient.nickname}) {patient.last_name}"
            return f"{patient.first_name} {patient.last_name}"

        # Labs
        if order_type in ("all", "lab"):
            lab_filters = {"date_ordered__gte": start, "date_ordered__lte": end}
            if staff_id != "all":
                lab_filters["ordering_provider__id"] = staff_id
            labs = (
                LabOrder.objects.filter(**lab_filters)
                .select_related("patient", "ordering_provider")
                .prefetch_related("tests")
                .order_by("-date_ordered")
            )
            for lab in labs:
                if not lab.patient:
                    continue
                test_names = list(lab.tests.values_list("ontology_test_name", flat=True))
                rows.append({
                    "patient_name": _patient_name(lab.patient) or "Unknown",
                    "chart_link": f"/patient/{lab.patient.id}",
                    "order_type": "Lab",
                    "description": ", ".join(test_names) if test_names else lab.comment or "Lab Order",
                    "date_ordered": arrow.get(lab.date_ordered).format("MMM DD, YYYY") if lab.date_ordered else "Unknown",
                    "provider": lab.ordering_provider.credentialed_name if lab.ordering_provider else "Unknown",
                })

        # Imaging
        if order_type in ("all", "imaging"):
            imaging_filters = {"date_time_ordered__gte": start, "date_time_ordered__lte": end}
            if staff_id != "all":
                imaging_filters["ordering_provider__id"] = staff_id
            imaging_orders = (
                ImagingOrder.objects.filter(**imaging_filters)
                .select_related("patient", "ordering_provider")
                .order_by("-date_time_ordered")
            )
            for img in imaging_orders:
                if not img.patient:
                    continue
                rows.append({
                    "patient_name": _patient_name(img.patient) or "Unknown",
                    "chart_link": f"/patient/{img.patient.id}",
                    "order_type": "Imaging",
                    "description": img.imaging or "Imaging Order",
                    "date_ordered": arrow.get(img.date_time_ordered).format("MMM DD, YYYY") if img.date_time_ordered else "Unknown",
                    "provider": img.ordering_provider.credentialed_name if img.ordering_provider else "Unknown",
                })

        # Referrals (including DME detection)
        if order_type in ("all", "referral", "dme"):
            ref_filters = {"date_referred__gte": start, "date_referred__lte": end}
            if staff_id != "all":
                ref_filters["note__provider__id"] = staff_id
            referrals = (
                Referral.objects.filter(**ref_filters)
                .select_related("patient", "note__provider")
                .order_by("-date_referred")
            )
            for ref in referrals:
                if not ref.patient:
                    continue
                is_dme = _is_dme_referral(ref.notes)
                ref_type = "DME" if is_dme else "Referral"
                if order_type == "dme" and not is_dme:
                    continue
                if order_type == "referral" and is_dme:
                    continue
                provider_name = "Unknown"
                if ref.note and ref.note.provider:
                    provider_name = ref.note.provider.credentialed_name
                rows.append({
                    "patient_name": _patient_name(ref.patient) or "Unknown",
                    "chart_link": f"/patient/{ref.patient.id}",
                    "order_type": ref_type,
                    "description": ref.notes or "Referral",
                    "date_ordered": arrow.get(ref.date_referred).format("MMM DD, YYYY") if ref.date_referred else "Unknown",
                    "provider": provider_name,
                })

        return [JSONResponse({
            "period": period,
            "order_type": order_type,
            "count": len(rows),
            "orders": rows,
        }, status_code=HTTPStatus.OK)]

    @api.get("/api/medications")
    def get_medications(self) -> list[Response | Effect]:
        """Return medications prescribed within the period."""
        staff_id = self._resolve_staff_id()
        period = self.request.query_params.get("period", "day")
        start, end = _get_date_range(period)

        med_filters = {"start_date__gte": start, "start_date__lte": end}
        if staff_id != "all":
            # Scope to patients seen by this provider
            visible_note_ids = self._get_visible_note_ids(staff_id, start, end)
            patient_ids = list(
                Note.objects.filter(dbid__in=visible_note_ids)
                .values_list("patient__id", flat=True)
                .distinct()
            )
            med_filters["patient__id__in"] = patient_ids

        medications = (
            Medication.objects.filter(**med_filters)
            .select_related("patient", "committer")
            .prefetch_related("codings")
            .order_by("-start_date")
        )

        rows = []
        for med in medications:
            patient = med.patient
            if not patient:
                continue
            full_name = (
                f"{patient.first_name} ({patient.nickname}) {patient.last_name}"
                if patient.nickname
                else f"{patient.first_name} {patient.last_name}"
            )
            # Get medication name from codings. `codings` is an unordered to-many,
            # so sort deterministically and pick the first coding that carries a
            # display name (avoids returning an arbitrary code as the name).
            codings = sorted(
                med.codings.all(), key=lambda c: (c.system or "", c.code or "")
            )
            med_name = next(
                (c.display for c in codings if c.display), "Unknown Medication"
            )

            date_prescribed = (
                arrow.get(med.start_date).format("MMM DD, YYYY")
                if med.start_date
                else "Unknown"
            )

            rows.append({
                "patient_name": full_name or "Unknown",
                "chart_link": f"/patient/{patient.id}",
                "medication_name": med_name,
                "date_prescribed": date_prescribed,
            })

        return [JSONResponse({
            "period": period,
            "count": len(rows),
            "medications": rows,
        }, status_code=HTTPStatus.OK)]
