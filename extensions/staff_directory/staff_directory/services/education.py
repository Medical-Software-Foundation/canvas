from __future__ import annotations

from staff_directory.models.education import Education
from staff_directory.models.extensions import CustomStaff


def list_for_staff(staff_dbid: int) -> list[Education]:
    return list(
        Education.objects.filter(staff__dbid=staff_dbid).order_by("-graduation_year", "institution")
    )


def get(entry_id: int) -> Education | None:
    return Education.objects.filter(dbid=entry_id).first()


def create(staff_dbid: int, data: dict) -> Education:
    staff = CustomStaff.objects.get(dbid=staff_dbid)
    return Education.objects.create(
        staff=staff,
        institution=_s(data.get("institution")),
        degree=_s(data.get("degree")),
        field_of_study=_s(data.get("field_of_study"), default=""),
        graduation_year=_int(data.get("graduation_year")),
        notes=_s(data.get("notes"), default=""),
    )


def update(entry_id: int, data: dict) -> Education | None:
    entry = get(entry_id)
    if entry is None:
        return None
    if "institution" in data:
        entry.institution = _s(data["institution"])
    if "degree" in data:
        entry.degree = _s(data["degree"])
    if "field_of_study" in data:
        entry.field_of_study = _s(data["field_of_study"], default="")
    if "graduation_year" in data:
        entry.graduation_year = _int(data["graduation_year"])
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


def serialize(entry: Education) -> dict:
    return {
        "id": entry.dbid,
        "institution": entry.institution,
        "degree": entry.degree,
        "field_of_study": entry.field_of_study,
        "graduation_year": entry.graduation_year or None,
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
