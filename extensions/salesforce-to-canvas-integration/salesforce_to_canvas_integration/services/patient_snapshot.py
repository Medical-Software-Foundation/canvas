"""Read a Canvas patient into the shared demographics compare shape.

The Synced and Activity surfaces, the Records details modal, and the automatic
modify apply all need the same snapshot of a linked Canvas patient, name, date
of birth, sex at birth, email, phone, mobile, and address, read straight from
the patient with its contact points and addresses. This module owns that read so
the status API and the webhook share one definition and can never drift. See
journal cnv-928/026 and cnv-938/032.
"""

from datetime import date
from typing import Any

from canvas_sdk.v1.data.common import ContactPointSystem, ContactPointUse
from canvas_sdk.v1.data.patient import Patient


def format_date(value: Any) -> str:
    """Render a ``Patient.birth_date`` for a JSON payload.

    Canvas returns ``birth_date`` as a :class:`datetime.date`, but ``.values``
    keeps whatever the column carries, so an unexpected string still serializes
    cleanly.
    """
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def patient_demographics(patient: Patient | None) -> dict[str, str]:
    """Snapshot a linked Canvas patient in the demographics compare shape.

    Reads name, date of birth, sex at birth, email, phone, mobile, and address
    straight from the patient with its contact points and addresses, so a linked
    row never depends on a captured event surviving. The phone and mobile split
    mirrors how the create effect writes them, a home use phone versus a mobile
    use phone. Pass a patient with ``telecom`` and ``addresses`` prefetched to
    keep this read free of extra round trips. See journal cnv-928/026.
    """
    if patient is None:
        return {}
    telecom = sorted(
        patient.telecom.all(),
        key=lambda cp: cp.rank if cp.rank is not None else 0,
    )

    def _first(system: str, *, mobile: bool | None = None) -> str:
        for cp in telecom:
            if cp.system != system:
                continue
            if mobile is True and cp.use != ContactPointUse.MOBILE:
                continue
            if mobile is False and cp.use == ContactPointUse.MOBILE:
                continue
            return str(cp.value or "")
        return ""

    addresses = list(patient.addresses.all())
    addr = addresses[0] if addresses else None
    return {
        "first_name": str(patient.first_name or ""),
        "last_name": str(patient.last_name or ""),
        "date_of_birth": format_date(patient.birth_date),
        "sex_at_birth": str(patient.sex_at_birth or ""),
        "email": _first(ContactPointSystem.EMAIL),
        "phone": _first(ContactPointSystem.PHONE, mobile=False),
        "mobile": _first(ContactPointSystem.PHONE, mobile=True),
        "address_line_1": str(getattr(addr, "line1", "") or ""),
        "address_line_2": str(getattr(addr, "line2", "") or ""),
        "city": str(getattr(addr, "city", "") or ""),
        "state": str(getattr(addr, "state_code", "") or ""),
        "postal_code": str(getattr(addr, "postal_code", "") or ""),
        "country": str(getattr(addr, "country", "") or ""),
    }


def canvas_demographics_by_id(patient_id: str | None) -> dict[str, str]:
    """Read the demographics snapshot for one linked patient by id.

    Returns an empty snapshot when the link points at no live patient. See
    journal cnv-928/026.
    """
    if not patient_id:
        return {}
    patient = (
        Patient.objects.filter(id=patient_id)
        .prefetch_related("telecom", "addresses")
        .first()
    )
    return patient_demographics(patient)


__all__ = (
    "canvas_demographics_by_id",
    "format_date",
    "patient_demographics",
)
