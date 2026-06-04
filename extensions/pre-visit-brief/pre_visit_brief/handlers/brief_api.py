"""Pre-Visit Brief SimpleAPI handler.

Serves the HTML shell, static assets, and JSON data for the prep-card modal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.note import Note, NoteTypeCategories
from canvas_sdk.v1.data.observation import Observation

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

# Appointment statuses that should be excluded from the brief.
_EXCLUDED_STATUSES = {
    AppointmentProgressStatus.CANCELLED,
    AppointmentProgressStatus.NOSHOWED,
}

# Observation `name` values that aren't real vitals and should be hidden.
# "Vital Signs Panel" is the parent record; "note" and "pulse_rhythm" are
# free-text annotations that don't render meaningfully as "label: value".
_SKIP_VITAL_NAMES = {"Vital Signs Panel", "note", "pulse_rhythm"}

# Canonical clinical display order for vitals.
_VITAL_ORDER = [
    "blood_pressure",
    "blood_pressure_systolic",
    "blood_pressure_diastolic",
    "pulse",
    "respiration_rate",
    "body_temperature",
    "oxygen_saturation",
    "weight",
    "height",
    "bmi",
    "waist_circumference",
    "head_circumference",
    "bmi_percentile",
    "weight_percentile",
    "height_percentile",
    "weight_for_length_percentile",
    "head_circumference_percentile",
]

# Friendly labels for common vital-sign observation names.
_VITAL_LABELS = {
    "blood_pressure": "BP",
    "blood_pressure_systolic": "BP (systolic)",
    "blood_pressure_diastolic": "BP (diastolic)",
    "pulse": "Pulse",
    "respiration_rate": "Respirations",
    "body_temperature": "Temp",
    "oxygen_saturation": "O2 sat",
    "weight": "Weight",
    "height": "Height",
    "waist_circumference": "Waist",
    "bmi": "BMI",
    "bmi_percentile": "BMI %ile",
    "weight_for_length_percentile": "Wt-for-length %ile",
    "head_circumference": "Head circ.",
    "head_circumference_percentile": "Head circ. %ile",
    "height_percentile": "Height %ile",
    "weight_percentile": "Weight %ile",
}


class BriefAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the pre-visit brief modal UI and data.

    Routes:
        GET /          – HTML shell (index.html)
        GET /main.js   – JavaScript asset
        GET /styles.css – CSS asset
        GET /data      – JSON prep-card data for today's upcoming appointments
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
        """Return JSON prep-card data for the logged-in provider's upcoming appointments.

        Query parameters:
            start (str): ISO-8601 datetime for the beginning of the day window (local TZ, from browser)
            end   (str): ISO-8601 datetime for the end of the day window (local TZ, from browser)

        Returns 400 if the staff UUID header is missing.
        Returns 400 if start/end params are missing or unparseable.
        """
        staff_uuid = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_uuid:
            return [
                JSONResponse(
                    {"error": "Missing canvas-logged-in-user-id header"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        start_str = self.request.query_params.get("start")
        end_str = self.request.query_params.get("end")
        if not start_str or not end_str:
            return [
                JSONResponse(
                    {"error": "Query parameters 'start' and 'end' are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)

        appointments = list(
            Appointment.objects.filter(
                provider__id=staff_uuid,
                start_time__gte=start_dt,
                start_time__lt=end_dt,
            )
            .exclude(status__in=list(_EXCLUDED_STATUSES))
            .select_related("patient", "note_type")
            .order_by("start_time")[:3]
        )

        if not appointments:
            return [JSONResponse({"appointments": []})]

        # patient_id on the Appointment FK is the integer DB PK (not the UUID).
        # We use that integer key consistently to cross-reference all bulk queries.
        raw_patient_ids = [
            appt.patient_id for appt in appointments if appt.patient_id is not None
        ]

        # Bulk-fetch all clinical data in one query per model – no N+1.
        conditions_qs = Condition.objects.filter(
            patient_id__in=raw_patient_ids,
            clinical_status="active",
            entered_in_error__isnull=True,
        ).prefetch_related("codings")

        allergies_qs = AllergyIntolerance.objects.filter(
            patient_id__in=raw_patient_ids,
            status="active",
            entered_in_error__isnull=True,
        )

        medications_qs = Medication.objects.filter(
            patient_id__in=raw_patient_ids,
            status="active",
            entered_in_error__isnull=True,
        ).prefetch_related("codings")

        observations_qs = (
            Observation.objects.filter(
                patient_id__in=raw_patient_ids,
                category__contains="vital-signs",
                entered_in_error__isnull=True,
            )
            .exclude(name__in=_SKIP_VITAL_NAMES)
            .order_by("-effective_datetime")
        )

        # One targeted query per patient instead of dragging the full encounter
        # history (and all its commands) across the wire just to render the
        # latest note per card. N is bounded to ≤3 by the appointment slice.
        latest_note_by_patient: dict[str, Note] = {}
        for patient_dbid in raw_patient_ids:
            note = (
                Note.objects.filter(
                    patient_id=patient_dbid,
                    note_type_version__category=NoteTypeCategories.ENCOUNTER,
                )
                .prefetch_related("commands")
                .order_by("-datetime_of_service")
                .first()
            )
            if note is not None:
                latest_note_by_patient[str(patient_dbid)] = note

        # Group each queryset by the integer patient_id (as string for dict key).
        conditions_by_patient: dict[str, list[Condition]] = {}
        for cond in conditions_qs:
            key = str(cond.patient_id)
            conditions_by_patient.setdefault(key, []).append(cond)

        allergies_by_patient: dict[str, list[AllergyIntolerance]] = {}
        for allergy in allergies_qs:
            key = str(allergy.patient_id)
            allergies_by_patient.setdefault(key, []).append(allergy)

        medications_by_patient: dict[str, list[Medication]] = {}
        for med in medications_qs:
            key = str(med.patient_id)
            medications_by_patient.setdefault(key, []).append(med)

        observations_by_patient: dict[str, list[Observation]] = {}
        for obs in observations_qs:
            key = str(obs.patient_id)
            observations_by_patient.setdefault(key, []).append(obs)

        cards = [
            _build_card(
                appt,
                conditions_by_patient,
                allergies_by_patient,
                medications_by_patient,
                observations_by_patient,
                latest_note_by_patient,
            )
            for appt in appointments
        ]

        return [JSONResponse({"appointments": cards})]


# ── Helpers ───────────────────────────────────────────────────────────────


def _build_card(
    appt: Appointment,
    conditions_by_patient: dict[str, list[Condition]],
    allergies_by_patient: dict[str, list[AllergyIntolerance]],
    medications_by_patient: dict[str, list[Medication]],
    observations_by_patient: dict[str, list[Observation]],
    latest_note_by_patient: dict[str, Note],
) -> dict[str, Any]:
    """Assemble a prep-card dict for a single appointment."""
    patient = appt.patient
    # patient_id on the Appointment FK is the integer DB PK – use it as the lookup key
    # to match the bulk-query grouping dicts.
    patient_key = str(appt.patient_id) if appt.patient_id is not None else ""
    # Use the UUID for the chart deep-link (visible to the browser).
    patient_uuid = str(patient.id) if patient else patient_key

    # Patient identity
    patient_name = (
        f"{patient.first_name} {patient.last_name}" if patient else "Unknown Patient"
    )

    # Appointment time / type
    start_iso = appt.start_time.isoformat() if appt.start_time else None
    note_type_name = appt.note_type.name if appt.note_type else "Visit"

    # Active conditions
    conditions = conditions_by_patient.get(patient_key, [])
    condition_list = _format_conditions(conditions)

    # Allergies
    allergies = allergies_by_patient.get(patient_key, [])
    allergy_list = [a.narrative for a in allergies if a.narrative] or ["None on record"]

    # Medications
    medications = medications_by_patient.get(patient_key, [])
    medication_list = _format_medications(medications)

    # Vitals – most recent value per vital name (no fixed cap)
    observations = observations_by_patient.get(patient_key, [])
    vital_list = _format_vitals(observations)

    # Last visit
    prior_note = latest_note_by_patient.get(patient_key)
    last_visit = _format_last_visit(prior_note)

    return {
        "patient_id": patient_uuid,
        "patient_name": patient_name,
        "start_time": start_iso,
        "note_type": note_type_name,
        "last_visit": last_visit,
        "conditions": condition_list,
        "allergies": allergy_list,
        "medications": medication_list,
        "vitals": vital_list,
    }


def _format_conditions(conditions: list[Condition]) -> list[str]:
    """Return a list of condition display strings."""
    if not conditions:
        return ["None on record"]
    result = []
    for cond in conditions:
        codings = list(cond.codings.all())
        if codings:
            coding = codings[0]
            label = coding.display or coding.code or "Unknown"
            code = coding.code or ""
            result.append(f"{label} ({code})" if code else label)
        else:
            result.append("Unknown condition")
    return result


def _format_medications(medications: list[Medication]) -> list[str]:
    """Return a list of medication display strings."""
    if not medications:
        return ["None on record"]
    result = []
    for med in medications:
        codings = list(med.codings.all())
        if codings:
            label = codings[0].display or codings[0].code or ""
        else:
            label = ""
        qty = med.clinical_quantity_description or ""
        display = " ".join(filter(None, [label, qty])) or "Unknown medication"
        result.append(display)
    return result


def _format_vitals(observations: list[Observation]) -> list[str]:
    """Return a list of vital-signs display strings.

    Keeps only the most recent value per vital `name` (observations are
    already ordered by `-effective_datetime` upstream), converts weight
    from oz to lbs, and renders in canonical clinical order.
    """
    latest: dict[str, Observation] = {}
    for obs in observations:
        if obs.name in _SKIP_VITAL_NAMES:
            continue
        if obs.name not in latest:
            latest[obs.name] = obs

    result = []
    for name in sorted(latest.keys(), key=_vital_sort_key):
        obs = latest[name]
        value = (obs.value or "").strip()
        if not value or value == "0":
            continue
        units = (obs.units or "").strip()
        if name == "weight" and units == "oz":
            value, units = _oz_to_lbs(value)
        label = _VITAL_LABELS.get(name, _humanize(name))
        display = f"{label}: {value} {units}".strip()
        result.append(display)
    if not result:
        return ["None on record"]
    return result


def _vital_sort_key(name: str) -> int:
    """Canonical sort order for vital signs; unknown names sort last."""
    try:
        return _VITAL_ORDER.index(name)
    except ValueError:
        return len(_VITAL_ORDER)


def _oz_to_lbs(value: str) -> tuple[str, str]:
    """Convert a weight in ounces to lbs, returning (value, units)."""
    try:
        lbs = float(value) / 16.0
    except ValueError:
        return value, "oz"
    formatted = f"{lbs:.1f}".rstrip("0").rstrip(".") or "0"
    return formatted, "lbs"


def _humanize(name: str) -> str:
    """Convert a snake_case observation name to a Title Case label."""
    return name.replace("_", " ").title() if name else "Vital"


def _format_last_visit(note: Note | None) -> dict[str, str | None]:
    """Return a dict with last-visit date and HPI/RFV snippet."""
    if note is None:
        return {"date": None, "snippet": "No prior visit on record"}

    date_str = (
        note.datetime_of_service.strftime("%b %-d, %Y")
        if note.datetime_of_service
        else None
    )

    snippet: str | None = None
    for cmd in note.commands.all():
        if cmd.schema_key == "hpi":
            narrative = (cmd.data or {}).get("narrative", "")
            if narrative:
                snippet = narrative[:120] + ("..." if len(narrative) > 120 else "")
                break

    if snippet is None:
        for cmd in note.commands.all():
            if cmd.schema_key == "reasonForVisit":
                comment = (cmd.data or {}).get("comment", "")
                if comment:
                    snippet = comment[:120] + ("..." if len(comment) > 120 else "")
                    break

    return {
        "date": date_str,
        "snippet": snippet or "No summary available",
    }
