from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.immunization import Immunization, ImmunizationStatement
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.questionnaire import Interview

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

SECTION_KEYS = (
    "socialDeterminants",
    "conditions",
    "medications",
    "allergies",
    "vitals",
    "immunizations",
    "surgicalHistory",
)

# Vital-type rows in the vitals table. Keys match the name used in each
# Observation that hangs off a "Vital Signs Panel" (with the one exception
# that "bp" is our alias for the combined systolic/diastolic value that the
# Observation row stores under `name="blood_pressure"`).
VITAL_TYPES: tuple[dict, ...] = (
    {"key": "bp", "label": "Blood pressure", "units": "mmHg"},
    {"key": "pulse", "label": "Pulse", "units": "bpm"},
    {"key": "respiration_rate", "label": "Respiration", "units": "/min"},
    {"key": "oxygen_saturation", "label": "O\u2082 saturation", "units": "%"},
    {"key": "body_temperature", "label": "Body temp", "units": "\u00b0F"},
    {"key": "weight_lbs", "label": "Weight", "units": "lbs"},
    {"key": "height", "label": "Height", "units": "in"},
    {"key": "waist_circumference", "label": "Waist", "units": "cm"},
)

_DIRECT_VITAL_NAMES = frozenset(
    {"pulse", "respiration_rate", "oxygen_saturation", "body_temperature", "height", "waist_circumference"}
)
_SKIP_VITAL_NAMES = frozenset({"note", "pulse_rhythm"})
_VITALS_MAX_PANELS = 12


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _primary_coding(obj) -> dict:
    # Most SDK records expose related codings as `.codings` (plural). A few
    # (notably ImmunizationStatement) use `.coding` (singular) — accept both.
    manager = getattr(obj, "codings", None) or getattr(obj, "coding", None)
    if manager is None:
        return {}
    first = manager.first()
    if not first:
        return {}
    return {
        "code": first.code or "",
        "display": first.display or "",
        "system": first.system or "",
    }


def _display_name(obj, fallback: str = "") -> str:
    primary = _primary_coding(obj)
    return primary.get("display") or fallback


def _serialize_condition(condition) -> dict:
    return {
        "id": str(condition.id),
        "name": _display_name(condition),
        "clinical_status": condition.clinical_status or "",
        "onset_date": _iso(condition.onset_date),
        "resolution_date": _iso(condition.resolution_date),
        "coding": _primary_coding(condition),
    }


def _serialize_medication(medication) -> dict:
    return {
        "id": str(medication.id),
        "name": _display_name(medication),
        "status": medication.status or "",
        "sig": medication.clinical_quantity_description or "",
        "start_date": _iso(medication.start_date),
        "end_date": _iso(medication.end_date),
    }


def _serialize_allergy(allergy) -> dict:
    return {
        "id": str(allergy.id),
        "name": _display_name(allergy),
        "severity": allergy.severity or "",
        "status": allergy.status or "",
        "narrative": allergy.narrative or "",
        "onset_date": _iso(allergy.onset_date),
    }


def _weight_oz_to_lbs(raw: str) -> str:
    try:
        oz = float(raw)
    except (TypeError, ValueError):
        return raw
    lbs = oz / 16.0
    if lbs >= 1:
        return str(int(round(lbs)))
    return f"{lbs:.1f}"


def _normalize_vital_members(members) -> dict[str, str]:
    """Map the Observation rows that hang off a Vital Signs Panel onto our
    `VITAL_TYPES` keys."""
    values: dict[str, str] = {}
    for member in members:
        name = (getattr(member, "name", "") or "").strip()
        raw = (getattr(member, "value", "") or "").strip()
        if not name or name in _SKIP_VITAL_NAMES or not raw:
            continue
        if name == "blood_pressure":
            values["bp"] = raw
        elif name == "weight":
            values["weight_lbs"] = _weight_oz_to_lbs(raw)
        elif name in _DIRECT_VITAL_NAMES:
            values[name] = raw
    return values


def _serialize_immunization(immunization) -> dict:
    return {
        "id": str(immunization.id),
        "kind": "administered",
        "name": _display_name(immunization),
        "date": _iso(immunization.date_ordered),
        "comment": immunization.sig_original or "",
    }


def _serialize_immunization_statement(statement) -> dict:
    return {
        "id": str(statement.id),
        "kind": "statement",
        "name": _display_name(statement, fallback=""),
        "date": _iso(statement.date),
        "comment": statement.comment or "",
    }


def _serialize_interview_response(response) -> dict:
    question = getattr(response, "question", None)
    value = (
        response.response_option_value
        or (getattr(response.response_option, "value", "") if response.response_option else "")
        or (response.comment or "")
    )
    return {
        "id": str(response.id),
        "question": (question.name if question else "").strip(),
        "value": (value or "").strip(),
        "recorded_at": _iso(getattr(response, "modified", None)),
    }


def build_conditions(patient_id: str) -> list[dict]:
    qs = (
        Condition.objects.for_patient(patient_id)
        .committed()
        .filter(surgical=False)
        .order_by("-onset_date")
    )
    return [_serialize_condition(c) for c in qs]


def build_surgical_history(patient_id: str) -> list[dict]:
    qs = (
        Condition.objects.for_patient(patient_id)
        .committed()
        .filter(surgical=True)
        .order_by("-onset_date")
    )
    return [_serialize_condition(c) for c in qs]


def build_medications(patient_id: str) -> list[dict]:
    qs = (
        Medication.objects.for_patient(patient_id)
        .committed()
        .order_by("-start_date")
    )
    return [_serialize_medication(m) for m in qs]


def build_allergies(patient_id: str) -> list[dict]:
    qs = (
        AllergyIntolerance.objects.for_patient(patient_id)
        .committed()
        .order_by("-recorded_date")
    )
    return [_serialize_allergy(a) for a in qs]


def build_vitals(patient_id: str) -> dict:
    panels = list(
        Observation.objects.for_patient(patient_id)
        .committed()
        .filter(category="vital-signs", name="Vital Signs Panel")
        .order_by("-effective_datetime")[:_VITALS_MAX_PANELS]
    )
    serialized = []
    for panel in panels:
        members = Observation.objects.committed().filter(is_member_of=panel)
        serialized.append(
            {
                "id": str(panel.id),
                "effective_datetime": _iso(panel.effective_datetime),
                "values": _normalize_vital_members(members),
            }
        )
    return {"types": list(VITAL_TYPES), "panels": serialized}


def build_immunizations(patient_id: str) -> list[dict]:
    # Immunization / ImmunizationStatement lack committer / entered_in_error
    # columns, so the shared `.committed()` helper can't be used here — filter
    # by `deleted` instead.
    administered = (
        Immunization.objects.for_patient(patient_id)
        .filter(deleted=False)
        .order_by("-date_ordered")
    )
    statements = (
        ImmunizationStatement.objects.for_patient(patient_id)
        .filter(deleted=False)
        .order_by("-date")
    )
    rows = [_serialize_immunization(i) for i in administered] + [
        _serialize_immunization_statement(s) for s in statements
    ]
    rows.sort(key=lambda row: row.get("date") or "", reverse=True)
    return rows


def build_social_determinants(patient_id: str) -> list[dict]:
    interviews = (
        Interview.objects.for_patient(patient_id)
        .committed()
        .filter(questionnaires__use_in_shx=True)
        .distinct()
        .order_by("-modified")
    )
    rows: list[dict] = []
    for interview in interviews:
        responses = (
            interview.interview_responses.select_related("question", "response_option")
            .order_by("-modified")
        )
        for response in responses:
            serialized = _serialize_interview_response(response)
            if serialized["question"] and serialized["value"]:
                rows.append(serialized)
    return rows


SECTION_BUILDERS = {
    "conditions": build_conditions,
    "surgicalHistory": build_surgical_history,
    "medications": build_medications,
    "allergies": build_allergies,
    "vitals": build_vitals,
    "immunizations": build_immunizations,
    "socialDeterminants": build_social_determinants,
}


def _parse_sections(raw: str | None) -> list[str]:
    if not raw:
        return list(SECTION_KEYS)
    requested = [s.strip() for s in raw.split(",") if s.strip()]
    return [s for s in requested if s in SECTION_BUILDERS]


class SummaryAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the clinical summary HTML shell, static assets, and JSON bundle."""

    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {"cache_bust": _CACHE_BUST}),
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "no-store"},
            )
        ]

    @api.get("/data.json")
    def data(self) -> list[Response | Effect]:
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id query param is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        sections = _parse_sections(self.request.query_params.get("sections"))
        payload = {
            "patient_id": patient_id,
            "sections": {key: SECTION_BUILDERS[key](patient_id) for key in sections},
        }
        return [JSONResponse(payload)]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
