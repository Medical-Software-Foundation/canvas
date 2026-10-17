from django.db import IntegrityError
from django.db.models import Max
from django.db.models.query import QuerySet
from django.db.transaction import atomic

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import CreatePatientExternalIdentifier
from canvas_sdk.effects.patient_metadata import PatientMetadata
from patient_numbering.models import NumberingState, PatientNumber, PatientProxy

# Identifier system for the patient number. Staff search it with "!<number>".
IDENTIFIER_SYSTEM = "https://schemas.canvasmedical.com/patient-number"

# Patient metadata key. The profile field reads the number from here.
METADATA_KEY = "patient_number"

BACKFILL_COMPLETE = "backfill_complete"

# Two patients created at the same moment can both read the same max. The unique
# constraint rejects the second insert, and it retries with the next number.
MAX_ATTEMPTS = 10


def backfill_complete() -> bool:
    """Return True once every patient that existed at install time has a number."""
    return bool(NumberingState.objects.filter(name=BACKFILL_COMPLETE, enabled=True).exists())


def mark_backfill_complete() -> None:
    """Record that the backfill finished, so new patients are numbered as they are created."""
    NumberingState.objects.update_or_create(name=BACKFILL_COMPLETE, defaults={"enabled": True})


def assign_number(patient: PatientProxy) -> tuple[int, bool]:
    """Return (number, newly_assigned). A patient that already has a number keeps it."""
    existing = PatientNumber.objects.filter(patient=patient).first()
    if existing:
        return existing.number, False

    for _ in range(MAX_ATTEMPTS):
        try:
            with atomic():
                current = PatientNumber.objects.aggregate(highest=Max("number"))["highest"]
                record = PatientNumber.objects.create(patient=patient, number=(current or 0) + 1)
            return record.number, True
        except IntegrityError:
            # Either the number was taken or this patient was numbered concurrently.
            existing = PatientNumber.objects.filter(patient=patient).first()
            if existing:
                return existing.number, False

    raise RuntimeError(f"Could not assign a patient number after {MAX_ATTEMPTS} attempts")


def number_effects(patient_key: str, number: int) -> list[Effect]:
    """Write the number as an external identifier (for search) and as metadata (for the profile)."""
    value = str(number)
    return [
        CreatePatientExternalIdentifier(
            patient_id=patient_key, system=IDENTIFIER_SYSTEM, value=value
        ).create(),
        PatientMetadata(patient_id=patient_key, key=METADATA_KEY).upsert(value),
    ]


def unnumbered_patients() -> "QuerySet[PatientProxy]":
    """Patients without a number, oldest first, so the backfill follows creation order."""
    numbered = PatientNumber.objects.values_list("patient_id", flat=True)
    patients: QuerySet[PatientProxy] = PatientProxy.objects.exclude(dbid__in=numbered).order_by(
        "created", "dbid"
    )
    return patients
