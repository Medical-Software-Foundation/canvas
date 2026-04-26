from __future__ import annotations

from staff_directory.models.extensions import CustomStaff
from staff_directory.models.training import ClinicalTraining

ALLOWED_PROGRAM_TYPES = ("internship", "residency", "fellowship", "other")


def list_for_staff(staff_dbid: int) -> list[ClinicalTraining]:
    return list(
        ClinicalTraining.objects.filter(staff__dbid=staff_dbid).order_by(
            "-end_year", "institution"
        )
    )


def get(entry_id: int) -> ClinicalTraining | None:
    return ClinicalTraining.objects.filter(dbid=entry_id).first()


def create(staff_dbid: int, data: dict) -> ClinicalTraining:
    staff = CustomStaff.objects.get(dbid=staff_dbid)
    return ClinicalTraining.objects.create(
        staff=staff,
        institution=_s(data.get("institution")),
        program_type=_program_type(data.get("program_type")),
        specialty_area=_s(data.get("specialty_area"), default=""),
        start_year=_int(data.get("start_year")),
        end_year=_int(data.get("end_year")),
        notes=_s(data.get("notes"), default=""),
    )


def update(entry_id: int, data: dict) -> ClinicalTraining | None:
    entry = get(entry_id)
    if entry is None:
        return None
    if "institution" in data:
        entry.institution = _s(data["institution"])
    if "program_type" in data:
        entry.program_type = _program_type(data["program_type"])
    if "specialty_area" in data:
        entry.specialty_area = _s(data["specialty_area"], default="")
    if "start_year" in data:
        entry.start_year = _int(data["start_year"])
    if "end_year" in data:
        entry.end_year = _int(data["end_year"])
    if "notes" in data:
        entry.notes = _s(data["notes"], default="")
    entry.save()
    return entry


def delete(entry_id: int) -> bool:
    entry = get(entry_id)
    if entry is None:
        return False
    entry.delete()
    return True


def serialize(entry: ClinicalTraining) -> dict:
    return {
        "id": entry.dbid,
        "institution": entry.institution,
        "program_type": entry.program_type,
        "specialty_area": entry.specialty_area,
        "start_year": entry.start_year or None,
        "end_year": entry.end_year or None,
        "notes": entry.notes,
    }


def _s(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _int(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _program_type(value) -> str:
    raw = _s(value).lower()
    return raw if raw in ALLOWED_PROGRAM_TYPES else "other"
