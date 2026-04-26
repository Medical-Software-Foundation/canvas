from __future__ import annotations

from django.db import IntegrityError

from staff_directory.models.extensions import CustomStaff
from staff_directory.models.nucc import NuccTaxonomyCode
from staff_directory.models.specialty import StaffSpecialty
from staff_directory.services.nucc import serialize_nucc


class SpecialtyError(Exception):
    """Raised for user-visible specialty validation failures."""


def list_for_staff(staff_dbid: int) -> list[StaffSpecialty]:
    return list(
        StaffSpecialty.objects.filter(staff__dbid=staff_dbid)
        .select_related("nucc_code")
        .order_by("-is_primary", "nucc_code__classification")
    )


def get(entry_id: int) -> StaffSpecialty | None:
    return (
        StaffSpecialty.objects.filter(dbid=entry_id)
        .select_related("nucc_code")
        .first()
    )


def create(staff_dbid: int, nucc_code: str, is_primary: bool = False) -> StaffSpecialty:
    nucc_code = (nucc_code or "").strip()
    if not nucc_code:
        raise SpecialtyError("NUCC code is required.")

    code = NuccTaxonomyCode.objects.filter(code=nucc_code).first()
    if code is None:
        raise SpecialtyError(f"Unknown NUCC code: {nucc_code}")

    staff = CustomStaff.objects.get(dbid=staff_dbid)

    try:
        if is_primary:
            StaffSpecialty.objects.filter(
                staff__dbid=staff_dbid, is_primary=True
            ).update(is_primary=False)
        entry = StaffSpecialty.objects.create(
            staff=staff,
            nucc_code=code,
            is_primary=bool(is_primary),
        )
    except IntegrityError as exc:
        raise SpecialtyError(
            f"This staff member already has specialty {nucc_code}."
        ) from exc
    return entry


def set_primary(entry_id: int) -> StaffSpecialty | None:
    entry = get(entry_id)
    if entry is None:
        return None
    StaffSpecialty.objects.filter(
        staff__dbid=entry.staff_id, is_primary=True
    ).exclude(dbid=entry_id).update(is_primary=False)
    entry.is_primary = True
    entry.save()
    return entry


def delete(entry_id: int) -> bool:
    entry = get(entry_id)
    if entry is None:
        return False
    entry.delete()
    return True


def serialize(entry: StaffSpecialty) -> dict:
    return {
        "id": entry.dbid,
        "is_primary": entry.is_primary,
        **serialize_nucc(entry.nucc_code),
    }
