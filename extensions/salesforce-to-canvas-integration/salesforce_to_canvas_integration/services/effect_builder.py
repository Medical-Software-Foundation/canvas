"""Translate a :class:`MappedPatient` into Canvas Patient + metadata effects."""

from datetime import date, datetime
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import (
    Patient as PatientEffect,
    PatientAddress,
    PatientContactPoint,
    PatientExternalIdentifier,
    PatientMetadata,
)
from canvas_sdk.effects.task.task import AddTask
from canvas_sdk.v1.data.common import (
    AddressType,
    AddressUse,
    ContactPointSystem,
    ContactPointUse,
    PersonSex,
)
from canvas_sdk.v1.data.patient import Patient as PatientRecord

from salesforce_to_canvas_integration.services.field_mapping import MappedPatient

_SEX_AT_BIRTH = {
    "male": PersonSex.SEX_MALE,
    "female": PersonSex.SEX_FEMALE,
    "other": PersonSex.SEX_OTHER,
    "unknown": PersonSex.SEX_UNKNOWN,
}


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _contact_points(mapped: MappedPatient) -> list[PatientContactPoint]:
    points: list[PatientContactPoint] = []
    email = mapped.canvas_fields.get("email")
    phone = mapped.canvas_fields.get("phone")
    if email:
        points.append(
            PatientContactPoint(
                system=ContactPointSystem.EMAIL,
                value=str(email),
                use=ContactPointUse.HOME,
                rank=1,
            )
        )
    if phone:
        points.append(
            PatientContactPoint(
                system=ContactPointSystem.PHONE,
                value=str(phone),
                use=ContactPointUse.HOME,
                rank=1,
            )
        )
    for key, value in mapped.telecom.items():
        if key == "mobile" and value:
            points.append(
                PatientContactPoint(
                    system=ContactPointSystem.PHONE,
                    value=str(value),
                    use=ContactPointUse.MOBILE,
                    rank=2,
                )
            )
    return points


def _address(mapped: MappedPatient) -> PatientAddress | None:
    line1 = mapped.canvas_fields.get("address_line_1")
    if not line1:
        return None
    return PatientAddress(
        line1=str(line1),
        line2=mapped.canvas_fields.get("address_line_2"),
        country=str(mapped.canvas_fields.get("country") or "US"),
        city=mapped.canvas_fields.get("city"),
        state_code=mapped.canvas_fields.get("state"),
        postal_code=mapped.canvas_fields.get("postal_code"),
        use=AddressUse.HOME,
        type=AddressType.BOTH,
    )


def _metadata(metadata: dict[str, str]) -> list[PatientMetadata]:
    return [
        PatientMetadata(key=key, value=str(value))
        for key, value in metadata.items()
        if value
    ]


def _sex_at_birth(value: Any) -> PersonSex | None:
    if not value:
        return None
    return _SEX_AT_BIRTH.get(str(value).strip().lower())


def _existing_external_identifiers(
    canvas_patient_id: str,
) -> list[PatientExternalIdentifier]:
    """Read the patient's current external identifiers as effect dataclasses.

    A patient update reconciles the identifier set from the effect payload. An
    update that leaves identifiers out drops every existing one, including the
    Salesforce link that ties the patient to its Salesforce record. Reading the
    current set and passing it back through the update preserves all of them, so
    applying a modify or tagging a delete never orphans the patient. See journal
    cnv-909/098 finding F3 and the plan in cnv-909/099.
    """
    patient = PatientRecord.objects.filter(id=canvas_patient_id).first()
    if patient is None:
        return []
    return [
        PatientExternalIdentifier(system=identifier.system, value=identifier.value)
        for identifier in patient.external_identifiers.all()
    ]


def build_create_patient_effect(
    *,
    mapped: MappedPatient,
    sf_record_id: str,
) -> Effect:
    """Build a ``Patient.create()`` effect from a mapped record."""
    address = _address(mapped)
    patient = PatientEffect(
        first_name=mapped.canvas_fields.get("first_name"),
        last_name=mapped.canvas_fields.get("last_name"),
        birthdate=_coerce_date(mapped.canvas_fields.get("date_of_birth")),
        sex_at_birth=_sex_at_birth(mapped.canvas_fields.get("sex_at_birth")),
        contact_points=_contact_points(mapped) or None,
        addresses=[address] if address else None,
        external_identifiers=[
            PatientExternalIdentifier(system="salesforce", value=sf_record_id)
        ],
        metadata=_metadata(dict(mapped.metadata)),
    )
    return patient.create()


def build_update_patient_effect(
    *,
    canvas_patient_id: str,
    mapped: MappedPatient,
) -> Effect:
    """Build a ``Patient.update()`` effect that delta-applies demographics.

    Only fields present in ``mapped.canvas_fields`` (plus contact points,
    address, and metadata when they carry content) cross over into the effect.
    Absent keys are not passed to :class:`PatientEffect` at all, so they stay
    out of the dirty set and Canvas leaves the existing value alone. See
    journal cnv-909/075, Q1, the delta apply decision.
    """
    kwargs: dict[str, Any] = {"patient_id": canvas_patient_id}

    fields = mapped.canvas_fields
    if "first_name" in fields:
        kwargs["first_name"] = fields["first_name"]
    if "last_name" in fields:
        kwargs["last_name"] = fields["last_name"]
    if "date_of_birth" in fields:
        birthdate = _coerce_date(fields["date_of_birth"])
        if birthdate is not None:
            kwargs["birthdate"] = birthdate
    if "sex_at_birth" in fields:
        sex = _sex_at_birth(fields["sex_at_birth"])
        if sex is not None:
            kwargs["sex_at_birth"] = sex

    contact_points = _contact_points(mapped)
    if contact_points:
        kwargs["contact_points"] = contact_points

    address = _address(mapped)
    if address is not None:
        kwargs["addresses"] = [address]

    metadata = _metadata(dict(mapped.metadata))
    if metadata:
        kwargs["metadata"] = metadata

    # Carry the existing external identifiers through the update so Canvas does
    # not drop the Salesforce link when it reconciles the identifier set. See
    # journal cnv-909/098 F3.
    preserved = _existing_external_identifiers(canvas_patient_id)
    if preserved:
        kwargs["external_identifiers"] = preserved

    patient = PatientEffect(**kwargs)
    return patient.update()


SALESFORCE_DELETED_AT_METADATA_KEY = "salesforce_deleted_at"


def build_tag_deleted_effect(
    *,
    canvas_patient_id: str,
    deleted_at: datetime,
) -> Effect:
    """Build a ``Patient.update()`` effect that tags the patient as SF deleted.

    Writes a single :class:`PatientMetadata` entry under the
    ``salesforce_deleted_at`` key carrying the ISO 8601 timestamp of the
    Salesforce delete event. No demographic columns are passed, so the delta
    apply contract from journal cnv-909/075 keeps every other field untouched.
    The patient's existing external identifiers ride along so the update does
    not drop the Salesforce link while tagging the delete. See cnv-909/098 F3.
    """
    kwargs: dict[str, Any] = {
        "patient_id": canvas_patient_id,
        "metadata": [
            PatientMetadata(
                key=SALESFORCE_DELETED_AT_METADATA_KEY,
                value=deleted_at.isoformat(),
            )
        ],
    }
    preserved = _existing_external_identifiers(canvas_patient_id)
    if preserved:
        kwargs["external_identifiers"] = preserved

    patient = PatientEffect(**kwargs)
    return patient.update()


def build_manual_review_task(
    *,
    sf_record_id: str,
    candidate_ids: tuple[str, ...],
    assignee_id: str | None = None,
) -> Effect:
    """Create the "manual review required" task when 2+ patients match.

    The candidate ids are appended to the title so reviewers can identify the
    conflict without opening the linked record. ``AddTaskComment`` is a
    separate effect that takes a task id we do not yet have, so we keep the
    initial task self-contained.
    """
    candidates_text = ", ".join(candidate_ids) or "—"
    task = AddTask(
        title=(
            f"Salesforce sync — manual review required for {sf_record_id} "
            f"(candidates: {candidates_text})"
        ),
        labels=["salesforce-sync", "manual-review"],
        assignee_id=assignee_id,
    )
    return task.apply()


_FORM_EDITABLE_KEYS: tuple[str, ...] = (
    "first_name",
    "last_name",
    "date_of_birth",
    "sex_at_birth",
    "email",
    "phone",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "postal_code",
    "country",
)


def build_mapped_patient_from_form(
    *,
    form: dict[str, Any],
    metadata: dict[str, str],
    telecom: dict[str, str],
) -> MappedPatient:
    """Build a MappedPatient from edited form fields plus captured metadata.

    Only known editable keys cross over from the form body, so an unknown key
    cannot spoof a SDK field. Metadata rides through unchanged because the
    first cut of the audit form does not edit it. Telecom rides through too,
    except the mobile phone, which the form may overwrite or clear.
    """
    canvas_fields: dict[str, Any] = {}
    for key in _FORM_EDITABLE_KEYS:
        value = form.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            canvas_fields[key] = text

    merged_telecom: dict[str, str] = dict(telecom)
    mobile = form.get("telecom_mobile")
    if mobile is not None:
        mobile_text = str(mobile).strip()
        if mobile_text:
            merged_telecom["mobile"] = mobile_text
        else:
            merged_telecom.pop("mobile", None)

    return MappedPatient(
        canvas_fields=canvas_fields,
        metadata=dict(metadata),
        telecom=merged_telecom,
    )


__all__ = (
    "SALESFORCE_DELETED_AT_METADATA_KEY",
    "build_create_patient_effect",
    "build_manual_review_task",
    "build_mapped_patient_from_form",
    "build_tag_deleted_effect",
    "build_update_patient_effect",
)
