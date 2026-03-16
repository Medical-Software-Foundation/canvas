"""SimpleAPI endpoints for patient CSV upload, validation, creation, and template download."""

from __future__ import annotations

import datetime
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import Patient, PatientAddress, PatientContactPoint, PatientExternalIdentifier
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data.common import AddressUse, ContactPointSystem, ContactPointUse, PersonSex
from logger import log

from patient_csv_loader.apps.csv_parser import ParseResult, generate_template_csv, parse_csv
from patient_csv_loader.apps.s3_client import upload_csv_to_s3

SEX_MAP: dict[str, PersonSex] = {
    "F": PersonSex.SEX_FEMALE,
    "M": PersonSex.SEX_MALE,
    "O": PersonSex.SEX_OTHER,
    "UNK": PersonSex.SEX_UNKNOWN,
}

ADDRESS_USE_MAP: dict[str, AddressUse] = {
    "home": AddressUse.HOME,
    "work": AddressUse.WORK,
    "temp": AddressUse.TEMP,
    "old": AddressUse.OLD,
}

CONTACT_SYSTEM_MAP: dict[str, ContactPointSystem] = {
    "phone": ContactPointSystem.PHONE,
    "fax": ContactPointSystem.FAX,
    "email": ContactPointSystem.EMAIL,
    "pager": ContactPointSystem.PAGER,
    "other": ContactPointSystem.OTHER,
}

CONTACT_USE_MAP: dict[str, ContactPointUse] = {
    "home": ContactPointUse.HOME,
    "work": ContactPointUse.WORK,
    "temp": ContactPointUse.TEMP,
    "old": ContactPointUse.OLD,
    "other": ContactPointUse.OTHER,
    "mobile": ContactPointUse.MOBILE,
    "automation": ContactPointUse.AUTOMATION,
}


def _to_digits(value: str) -> str:
    """Extract only digit characters from a string."""
    return "".join(ch for ch in value if ch.isdigit())


def _build_contact_points(row: dict[str, str | None]) -> list[PatientContactPoint]:
    """Build PatientContactPoint list from a validated row."""
    contacts: list[PatientContactPoint] = []

    # Required phone field → rank 1 mobile contact (normalized to 10 digits)
    phone = (row.get("phone") or "").strip()
    if phone:
        contacts.append(
            PatientContactPoint(
                system=ContactPointSystem.PHONE,
                value=_to_digits(phone),
                use=ContactPointUse.MOBILE,
                rank=1,
            )
        )

    # Optional contact slots (1 and 2)
    for slot, default_rank in ((1, 2), (2, 3)):
        prefix = f"contact_{slot}_"
        system_str = (row.get(f"{prefix}system") or "").strip().lower()
        value = (row.get(f"{prefix}value") or "").strip()
        if not system_str or not value:
            continue

        use_str = (row.get(f"{prefix}use") or "home").strip().lower()
        rank_str = (row.get(f"{prefix}rank") or "").strip()
        has_consent_str = (row.get(f"{prefix}has_consent") or "").strip().lower()

        rank = int(rank_str) if rank_str else default_rank
        has_consent = has_consent_str == "true" if has_consent_str else None

        # Normalize phone values to digits only per FHIR spec
        normalized_value = _to_digits(value) if system_str == "phone" else value

        contacts.append(
            PatientContactPoint(
                system=CONTACT_SYSTEM_MAP[system_str],
                value=normalized_value,
                use=CONTACT_USE_MAP.get(use_str, ContactPointUse.HOME),
                rank=rank,
                has_consent=has_consent,
            )
        )

    return contacts


def _build_address(row: dict[str, str | None]) -> PatientAddress | None:
    """Build a PatientAddress from a validated row, or None if no address fields."""
    line1 = (row.get("address_line1") or "").strip()
    if not line1:
        return None

    use_str = (row.get("address_use") or "home").strip().lower()

    return PatientAddress(
        line1=line1,
        line2=(row.get("address_line2") or "").strip() or None,
        city=(row.get("address_city") or "").strip(),
        state_code=(row.get("address_state_code") or "").strip().upper(),
        postal_code=_to_digits((row.get("address_postal_code") or "").strip()),
        country=(row.get("address_country") or "").strip().upper(),
        use=ADDRESS_USE_MAP.get(use_str, AddressUse.HOME),
    )


def _build_external_identifiers(row: dict[str, str | None]) -> list[PatientExternalIdentifier]:
    """Build PatientExternalIdentifier list from a validated row."""
    identifiers: list[PatientExternalIdentifier] = []
    for slot in (1, 2, 3):
        system = (row.get(f"external_id_{slot}_system") or "").strip()
        value = (row.get(f"external_id_{slot}_value") or "").strip()
        if system and value:
            identifiers.append(PatientExternalIdentifier(system=system, value=value))
    return identifiers


def _normalize_ssn(value: str) -> str | None:
    """Strip dashes/spaces from SSN to get 9 digits only. Returns None if empty."""
    raw = value.strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits or None


def _build_patient_effect(row: dict[str, str | None]) -> Effect:
    """Build a Patient.create() effect from a validated row."""
    sex_str = (row.get("sex_at_birth") or "").strip().upper()

    patient = Patient(
        first_name=(row.get("first_name") or "").strip(),
        last_name=(row.get("last_name") or "").strip(),
        middle_name=(row.get("middle_name") or "").strip() or None,
        birthdate=datetime.date.fromisoformat((row.get("birthdate") or "").strip()),
        prefix=(row.get("prefix") or "").strip() or None,
        suffix=(row.get("suffix") or "").strip() or None,
        sex_at_birth=SEX_MAP.get(sex_str),
        nickname=(row.get("nickname") or "").strip() or None,
        social_security_number=_normalize_ssn(row.get("social_security_number") or ""),
        administrative_note=(row.get("administrative_note") or "").strip() or None,
        clinical_note=(row.get("clinical_note") or "").strip() or None,
        contact_points=_build_contact_points(row),
        external_identifiers=_build_external_identifiers(row) or None,
        addresses=[addr] if (addr := _build_address(row)) else None,
    )
    return patient.create()


class PatientCSVAPI(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for patient CSV upload, validation, and creation."""

    PREFIX = "/csv"

    @api.post("/validate")
    def validate_csv(self) -> list[Response | Effect]:
        """Receive a CSV file via multipart form, parse and validate it."""
        form_data = self.request.form_data()
        file_part = form_data.get("file")

        if file_part is None or not file_part.is_file():
            return [
                JSONResponse(
                    {"error": "No CSV file provided. Upload a file with field name 'file'."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        csv_content = file_part.content.decode("utf-8-sig")
        result: ParseResult = parse_csv(csv_content)

        # Upload CSV to S3 for audit trail
        warnings: list[str] = []
        bucket = self.secrets.get("S3_BUCKET_NAME", "")
        access_key = self.secrets.get("AWS_ACCESS_KEY_ID", "")
        secret_key = self.secrets.get("AWS_SECRET_ACCESS_KEY", "")
        if bucket and access_key and secret_key:
            filename = getattr(file_part, "filename", "upload.csv") or "upload.csv"
            uploaded = upload_csv_to_s3(
                csv_content=csv_content,
                filename=filename,
                bucket=bucket,
                access_key_id=access_key,
                secret_access_key=secret_key,
            )
            if not uploaded:
                warnings.append("Unable to save CSV to S3 for audit trail. The file was not archived.")
        else:
            log.warning("Patient CSV Loader: S3 secrets not configured, skipping audit upload")
            warnings.append("S3 audit trail is not configured. Uploaded files will not be archived.")

        return [
            JSONResponse({
                "total_rows": result.total_rows,
                "valid_count": len(result.valid_rows),
                "error_count": len(result.error_rows),
                "warnings": warnings,
                "valid_rows": [
                    {"row_number": r.row_number, "data": r.data}
                    for r in result.valid_rows
                ],
                "error_rows": [
                    {"row_number": r.row_number, "errors": r.errors, "data": r.raw_data}
                    for r in result.error_rows
                ],
            })
        ]

    @api.post("/create")
    def create_patients(self) -> list[Response | Effect]:
        """Create patients from previously validated rows."""
        body = self.request.json()
        rows = body.get("rows", [])

        if not rows:
            return [
                JSONResponse(
                    {"error": "No rows provided."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        effects: list[Response | Effect] = []
        created_count = 0

        for row_data in rows:
            data = row_data.get("data", {})
            try:
                effect = _build_patient_effect(data)
                effects.append(effect)
                created_count += 1
            except Exception as exc:
                log.error(f"Failed to build patient effect for row: {exc}")

        log.info(f"Patient CSV Loader: submitting {created_count} patient create effects")

        effects.append(
            JSONResponse({
                "submitted_count": created_count,
                "total_requested": len(rows),
            })
        )

        return effects

    @api.get("/template")
    def download_template(self) -> list[Response | Effect]:
        """Return a downloadable CSV template."""
        csv_content = generate_template_csv()
        return [
            Response(
                csv_content.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={
                    "Content-Type": "text/csv",
                    "Content-Disposition": 'attachment; filename="patient_load_template.csv"',
                },
                content_type="text/csv",
            )
        ]
