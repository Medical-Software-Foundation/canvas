from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError
from django.db.models import Max
from django.db.models.query import QuerySet
from django.db.transaction import atomic

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import CreatePatientExternalIdentifier
from canvas_sdk.effects.patient_metadata import PatientMetadata
from canvas_sdk.v1.data import PatientExternalIdentifier
from patient_numbering.models import NumberingState, PatientNumber, PatientProxy

# Identifier system for the patient number. Staff search it with "!<number>".
IDENTIFIER_SYSTEM = "https://schemas.canvasmedical.com/patient-number"

# Patient metadata key. The profile field reads the number from here.
METADATA_KEY = "patient_number"

BACKFILL_COMPLETE = "backfill_complete"

# Two patients created at the same moment can both read the same max. The unique
# constraint rejects the second insert, and it retries with the next number.
MAX_ATTEMPTS = 10


@dataclass(frozen=True)
class NumberFormat:
    """How a Patient ID is displayed, and where existing IDs are adopted from.

    With every setting unset, Patient IDs are plain numbers (1, 2, 3...) and nothing is adopted.
    """

    prefix: str = ""
    width: int = 0
    source_system: str = ""

    @classmethod
    def from_secrets(cls, secrets: Any) -> "NumberFormat":
        """Read NUMBER_PREFIX, NUMBER_WIDTH and SOURCE_IDENTIFIER_SYSTEM. Unset or invalid means off."""
        raw_width = (secrets.get("NUMBER_WIDTH") or "").strip()
        return cls(
            prefix=(secrets.get("NUMBER_PREFIX") or "").strip(),
            width=int(raw_width) if raw_width.isascii() and raw_width.isdigit() else 0,
            source_system=(secrets.get("SOURCE_IDENTIFIER_SYSTEM") or "").strip(),
        )

    def format(self, number: int) -> str:
        """Render a number as a Patient ID, for example 349 -> "ABC0349"."""
        return f"{self.prefix}{str(number).zfill(self.width)}"

    def parse(self, value: str) -> int | None:
        """Return the number in a source ID like "ABC0042", or None if it doesn't fit the format."""
        value = value.strip()
        if not value.startswith(self.prefix):
            return None
        digits = value[len(self.prefix) :]
        if not (digits.isascii() and digits.isdigit()):
            return None
        number = int(digits)
        return number if number > 0 else None


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


def adopt_number(patient: PatientProxy, number: int) -> bool:
    """Give the patient a specific number. Return False if that number already belongs to someone else."""
    try:
        with atomic():
            PatientNumber.objects.create(patient=patient, number=number)
    except IntegrityError:
        return False
    return True


def source_numbers(fmt: NumberFormat) -> dict[int, tuple[int, str]]:
    """Map patient dbid -> (number, raw value) of that patient's source ID, for unnumbered patients only.

    A patient with no source ID, or one that doesn't match the format, is left out.
    """
    if not fmt.source_system:
        return {}
    numbered = set(PatientNumber.objects.values_list("patient_id", flat=True))
    found: dict[int, tuple[int, str]] = {}
    rows = PatientExternalIdentifier.objects.filter(
        system=fmt.source_system, patient__isnull=False
    ).values_list("patient_id", "value")
    for patient_dbid, value in rows:
        if patient_dbid in numbered or patient_dbid in found:
            continue
        number = fmt.parse(value or "")
        if number is not None:
            found[patient_dbid] = (number, value.strip())
    return found


def adoptable_patients(
    fmt: NumberFormat, limit: int | None = None
) -> tuple[list[tuple[PatientProxy, int, str]], int]:
    """Unnumbered patients whose source number is still free, oldest first, plus how many there are.

    Only `limit` patients are loaded; the count covers all of them, so the caller can tell whether
    more remain without a second pass. A patient whose source number is already taken is left out
    here and numbered sequentially afterwards, so a duplicate source ID can't stall the backfill.
    """
    by_patient = source_numbers(fmt)
    if not by_patient:
        return [], 0
    taken = set(PatientNumber.objects.values_list("number", flat=True))
    free = {dbid: found for dbid, found in by_patient.items() if found[0] not in taken}
    patients = PatientProxy.objects.filter(dbid__in=free.keys()).order_by("created", "dbid")
    if limit is not None:
        patients = patients[:limit]
    return [(patient, *free[patient.dbid]) for patient in patients], len(free)


def number_effects(
    patient_key: str,
    number: int,
    fmt: NumberFormat | None = None,
    searchable_as: str | None = None,
) -> list[Effect]:
    """Write the Patient ID as an external identifier (for search) and as metadata (for the profile).

    searchable_as is the patient's existing source ID. When it already reads exactly as the
    Patient ID, "!<id>" search finds the patient through it, so a second identifier with the same
    value is skipped: Canvas search would otherwise list the patient twice.
    """
    value = (fmt or NumberFormat()).format(number)
    metadata = PatientMetadata(patient_id=patient_key, key=METADATA_KEY).upsert(value)
    if searchable_as == value:
        return [metadata]
    return [
        CreatePatientExternalIdentifier(
            patient_id=patient_key, system=IDENTIFIER_SYSTEM, value=value
        ).create(),
        metadata,
    ]


def unnumbered_patients() -> "QuerySet[PatientProxy]":
    """Patients without a number, oldest first, so the backfill follows creation order."""
    numbered = PatientNumber.objects.values_list("patient_id", flat=True)
    patients: QuerySet[PatientProxy] = PatientProxy.objects.exclude(dbid__in=numbered).order_by(
        "created", "dbid"
    )
    return patients


def adopted_count(fmt: NumberFormat) -> int:
    """How many numbered patients carry the same number as their source ID."""
    if not fmt.source_system:
        return 0
    numbers = dict(PatientNumber.objects.values_list("patient_id", "number"))
    matched: set[int] = set()
    rows = PatientExternalIdentifier.objects.filter(
        system=fmt.source_system, patient__isnull=False
    ).values_list("patient_id", "value")
    for patient_dbid, value in rows:
        if patient_dbid in numbers and fmt.parse(value or "") == numbers[patient_dbid]:
            matched.add(patient_dbid)
    return len(matched)


def next_number() -> int:
    """The number the next new patient will get."""
    current = PatientNumber.objects.aggregate(highest=Max("number"))["highest"]
    return (current or 0) + 1
