import re
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import Patient as PatientEffect, PatientContactPoint
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.common import ContactPointSystem, ContactPointUse, PersonSex
from canvas_sdk.v1.data.patient import Patient

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))
_DOB_WINDOW = timedelta(days=365)
_VALID_SEX_VALUES = {c.value for c in PersonSex if c.value}


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _parse_dob(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _validate_submission(body: dict) -> tuple[dict | None, dict]:
    """Extract and validate submission fields. Returns (cleaned | None, errors)."""
    errors: dict = {}

    first_name = (body.get("first_name") or "").strip()
    last_name = (body.get("last_name") or "").strip()
    birth_date_str = (body.get("birth_date") or "").strip()
    sex_at_birth = (body.get("sex_at_birth") or "").strip()
    phone = (body.get("phone") or "").strip()

    if not first_name:
        errors["first_name"] = "First name is required."
    if not last_name:
        errors["last_name"] = "Last name is required."

    birth_date = _parse_dob(birth_date_str) if birth_date_str else None
    if not birth_date_str:
        errors["birth_date"] = "Date of birth is required."
    elif birth_date is None:
        errors["birth_date"] = "Date of birth must be a valid date (YYYY-MM-DD)."
    elif birth_date > date.today():
        errors["birth_date"] = "Date of birth cannot be in the future."

    if not sex_at_birth:
        errors["sex_at_birth"] = "Sex at birth is required."
    elif sex_at_birth not in _VALID_SEX_VALUES:
        errors["sex_at_birth"] = (
            f"Sex at birth must be one of: {', '.join(sorted(_VALID_SEX_VALUES))}."
        )

    phone_digits = _normalize_phone(phone)
    if not phone:
        errors["phone"] = "Phone number is required."
    elif len(phone_digits) < 10:
        errors["phone"] = "Phone number must contain at least 10 digits."

    if errors:
        return None, errors

    return (
        {
            "first_name": first_name,
            "last_name": last_name,
            "birth_date": birth_date,
            "sex_at_birth": sex_at_birth,
            "phone": phone,
            "phone_digits": phone_digits,
        },
        {},
    )


def _describe_dob_match(target: date, candidate: date) -> str:
    days_off = abs((candidate - target).days)
    if days_off == 0:
        return "name + dob"
    if days_off <= 7:
        return f"name, dob off by {days_off} day{'s' if days_off != 1 else ''}"
    return f"name, dob differs ({candidate.isoformat()})"


def _primary_phone(patient: Patient) -> str:
    phone_cp = patient.primary_phone_number
    return phone_cp.value if phone_cp else ""


def _serialize_duplicate(patient: Patient, reasons: list[str]) -> dict:
    return {
        "id": str(patient.id),
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
        "phone": _primary_phone(patient),
        "reasons": reasons,
    }


def _find_duplicates(cleaned: dict) -> list[dict]:
    target_name_key = _normalize_name(cleaned["first_name"]) + _normalize_name(cleaned["last_name"])
    dob = cleaned["birth_date"]
    phone_digits = cleaned["phone_digits"]

    by_id: dict[str, dict] = {}

    # Pass 1 — normalized name + DOB within ±1 year.
    name_candidates = Patient.objects.filter(
        birth_date__gte=dob - _DOB_WINDOW,
        birth_date__lte=dob + _DOB_WINDOW,
    )
    for candidate in name_candidates:
        candidate_key = _normalize_name(candidate.first_name) + _normalize_name(candidate.last_name)
        if candidate_key != target_name_key:
            continue
        reason = _describe_dob_match(dob, candidate.birth_date)
        by_id[str(candidate.id)] = _serialize_duplicate(candidate, [reason])

    # Pass 2 — same normalized phone digits.
    if len(phone_digits) >= 4:
        last4 = phone_digits[-4:]
        phone_candidates = (
            Patient.objects.filter(
                telecom__system=ContactPointSystem.PHONE,
                telecom__value__contains=last4,
            )
            .distinct()
        )
        for candidate in phone_candidates:
            matched = any(
                tc.system == ContactPointSystem.PHONE
                and _normalize_phone(tc.value) == phone_digits
                for tc in candidate.telecom.all()
            )
            if not matched:
                continue
            key = str(candidate.id)
            if key in by_id:
                by_id[key]["reasons"].append("phone")
            else:
                by_id[key] = _serialize_duplicate(candidate, ["phone"])

    return list(by_id.values())


class RegisterPatientAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the register-patient UI, duplicate detection, creation, and lookup endpoints."""

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

    @api.post("/check")
    def check(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        cleaned, errors = _validate_submission(body)
        if errors:
            return [JSONResponse({"errors": errors}, status_code=HTTPStatus.BAD_REQUEST)]
        duplicates = _find_duplicates(cleaned)
        return [JSONResponse({"duplicates": duplicates})]

    @api.post("/create")
    def create(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        cleaned, errors = _validate_submission(body)
        if errors:
            return [JSONResponse({"errors": errors}, status_code=HTTPStatus.BAD_REQUEST)]

        duplicates = _find_duplicates(cleaned)
        acknowledged = bool(body.get("acknowledged"))
        if duplicates and not acknowledged:
            return [
                JSONResponse(
                    {
                        "duplicates": duplicates,
                        "error": "Acknowledge potential duplicates before creating.",
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        effect = PatientEffect(
            first_name=cleaned["first_name"],
            last_name=cleaned["last_name"],
            birthdate=cleaned["birth_date"],
            sex_at_birth=PersonSex(cleaned["sex_at_birth"]),
            contact_points=[
                PatientContactPoint(
                    system=ContactPointSystem.PHONE,
                    value=cleaned["phone"],
                    use=ContactPointUse.MOBILE,
                    rank=1,
                )
            ],
        )

        lookup_started_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        return [
            effect.create(),
            JSONResponse(
                {
                    "status": "submitted",
                    "lookup_started_at": lookup_started_at.isoformat(),
                    "lookup_params": {
                        "first_name": cleaned["first_name"],
                        "last_name": cleaned["last_name"],
                        "birth_date": cleaned["birth_date"].isoformat(),
                    },
                },
                status_code=HTTPStatus.ACCEPTED,
            ),
        ]

    @api.get("/find")
    def find(self) -> list[Response | Effect]:
        params = self.request.query_params
        first_name = (params.get("first_name") or "").strip()
        last_name = (params.get("last_name") or "").strip()
        birth_date = _parse_dob((params.get("birth_date") or "").strip())
        after = _parse_datetime(params.get("after") or "")

        if not first_name or not last_name or not birth_date or not after:
            return [
                JSONResponse(
                    {"error": "first_name, last_name, birth_date, and after are required."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        candidate = (
            Patient.objects.filter(
                first_name=first_name,
                last_name=last_name,
                birth_date=birth_date,
                created__gte=after,
            )
            .order_by("-created")
            .first()
        )
        return [JSONResponse({"patient_id": str(candidate.id) if candidate else None})]

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
