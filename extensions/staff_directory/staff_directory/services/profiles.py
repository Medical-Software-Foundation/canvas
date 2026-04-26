from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from canvas_sdk.v1.data import Staff

from staff_directory.models.certification import BoardCertification
from staff_directory.models.education import Education
from staff_directory.models.extensions import CustomStaff
from staff_directory.models.specialty import StaffSpecialty
from staff_directory.models.training import ClinicalTraining
from staff_directory.services.certifications import (
    list_for_staff as cert_list_for_staff,
    serialize as cert_serialize,
    status as cert_status,
)
from staff_directory.services.education import (
    list_for_staff as edu_list_for_staff,
    serialize as edu_serialize,
)
from staff_directory.services.specialties import (
    list_for_staff as spec_list_for_staff,
    serialize as spec_serialize,
)
from staff_directory.services.training import (
    list_for_staff as train_list_for_staff,
    serialize as train_serialize,
)


def list_staff(
    search: str = "",
    specialty_code: str = "",
    expiring_within_days: int | None = None,
    today: date | None = None,
) -> list[dict]:
    today = today or date.today()

    queryset = CustomStaff.objects.filter(active=True)

    search = (search or "").strip()
    if search:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
        )

    specialty_code = (specialty_code or "").strip()
    if specialty_code:
        matching_staff_ids = list(
            StaffSpecialty.objects.filter(nucc_code__code=specialty_code)
            .values_list("staff_id", flat=True)
            .distinct()
        )
        queryset = queryset.filter(dbid__in=matching_staff_ids)

    if expiring_within_days is not None:
        cutoff = today + timedelta(days=max(0, int(expiring_within_days)))
        expiring_staff_ids = list(
            BoardCertification.objects.filter(
                expiration_date__isnull=False,
                expiration_date__lte=cutoff,
            )
            .values_list("staff_id", flat=True)
            .distinct()
        )
        queryset = queryset.filter(dbid__in=expiring_staff_ids)

    queryset = queryset.order_by("last_name", "first_name")

    staff_list = list(queryset)
    staff_ids = [s.dbid for s in staff_list]

    # Bulk-fetch related rows grouped by staff_id.
    certs_by_staff = _group_by_staff(
        BoardCertification.objects.filter(staff__dbid__in=staff_ids)
    )
    specialties_by_staff = _group_by_staff(
        StaffSpecialty.objects.filter(staff__dbid__in=staff_ids).select_related(
            "nucc_code"
        )
    )
    educations_by_staff = _group_by_staff(
        Education.objects.filter(staff__dbid__in=staff_ids)
    )
    trainings_by_staff = _group_by_staff(
        ClinicalTraining.objects.filter(staff__dbid__in=staff_ids)
    )

    return [
        _summarize(
            staff,
            today=today,
            certifications=certs_by_staff.get(staff.dbid, []),
            specialties=specialties_by_staff.get(staff.dbid, []),
            education_count=len(educations_by_staff.get(staff.dbid, [])),
            training_count=len(trainings_by_staff.get(staff.dbid, [])),
        )
        for staff in staff_list
    ]


def get_staff_profile(staff_dbid: int, today: date | None = None) -> dict | None:
    today = today or date.today()
    staff = CustomStaff.objects.filter(dbid=staff_dbid).first()
    if staff is None:
        return None

    certifications = cert_list_for_staff(staff_dbid)
    specialties = spec_list_for_staff(staff_dbid)
    educations = edu_list_for_staff(staff_dbid)
    trainings = train_list_for_staff(staff_dbid)

    summary = _summarize(
        staff,
        today=today,
        certifications=certifications,
        specialties=specialties,
        education_count=len(educations),
        training_count=len(trainings),
    )
    summary.update(
        {
            "educations": [edu_serialize(e) for e in educations],
            "trainings": [train_serialize(t) for t in trainings],
            "specialties": [spec_serialize(s) for s in specialties],
            "certifications": [
                cert_serialize(c, today=today) for c in certifications
            ],
        }
    )
    return summary


def get_staff_by_user_header(user_id: str) -> Staff | None:
    """Look up the logged-in user Staff record from the session header value.

    The `canvas-logged-in-user-id` header contains a UUID (possibly without dashes);
    Staff.id is a UUID so we query it directly, tolerating either form.
    """
    if not user_id:
        return None
    candidates = {user_id, user_id.replace("-", "")}
    return Staff.objects.filter(id__in=candidates).first()


def _group_by_staff(queryset) -> dict[int, list]:
    grouped: dict[int, list] = defaultdict(list)
    for item in queryset:
        grouped[item.staff_id].append(item)
    return grouped


def _summarize(
    staff,
    today: date,
    certifications: list,
    specialties: list,
    education_count: int,
    training_count: int,
) -> dict:
    primary_specialty = next(
        (s for s in specialties if s.is_primary),
        specialties[0] if specialties else None,
    )

    return {
        "id": str(staff.id),
        "dbid": staff.dbid,
        "first_name": staff.first_name,
        "last_name": staff.last_name,
        "full_name": _full_name(staff),
        "role": _role_name(staff),
        "primary_specialty": (
            {
                "code": primary_specialty.nucc_code.code,
                "display_name": primary_specialty.nucc_code.display_name,
            }
            if primary_specialty
            else None
        ),
        "education_count": education_count,
        "training_count": training_count,
        "specialty_count": len(specialties),
        "certification_count": len(certifications),
        "has_expiring_cert": any(
            cert_status(c, today=today) in ("expiring_soon", "expired")
            for c in certifications
        ),
    }


def _full_name(staff) -> str:
    first = (staff.first_name or "").strip()
    last = (staff.last_name or "").strip()
    combined = (first + " " + last).strip()
    return combined or getattr(staff, "credentialed_name", "") or ""


def _role_name(staff) -> str:
    top = getattr(staff, "top_clinical_role", None)
    if top is not None:
        return getattr(top, "display", None) or getattr(top, "internal_code", "") or ""
    return ""
