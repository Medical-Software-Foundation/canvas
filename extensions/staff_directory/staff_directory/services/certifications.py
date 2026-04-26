from __future__ import annotations

from datetime import date, datetime, timedelta

from staff_directory.models.certification import BoardCertification
from staff_directory.models.extensions import CustomStaff


def list_for_staff(staff_dbid: int) -> list[BoardCertification]:
    return list(
        BoardCertification.objects.filter(staff__dbid=staff_dbid).order_by(
            "expiration_date", "board_name"
        )
    )


def get(entry_id: int) -> BoardCertification | None:
    return BoardCertification.objects.filter(dbid=entry_id).first()


def create(staff_dbid: int, data: dict) -> BoardCertification:
    staff = CustomStaff.objects.get(dbid=staff_dbid)
    return BoardCertification.objects.create(
        staff=staff,
        board_name=_s(data.get("board_name")),
        specialty=_s(data.get("specialty")),
        certification_number=_s(data.get("certification_number"), default=""),
        issued_date=_date(data.get("issued_date")),
        expiration_date=_date(data.get("expiration_date")),
        notes=_s(data.get("notes"), default=""),
    )


def update(entry_id: int, data: dict) -> BoardCertification | None:
    entry = get(entry_id)
    if entry is None:
        return None
    if "board_name" in data:
        entry.board_name = _s(data["board_name"])
    if "specialty" in data:
        entry.specialty = _s(data["specialty"])
    if "certification_number" in data:
        entry.certification_number = _s(data["certification_number"], default="")
    if "issued_date" in data:
        entry.issued_date = _date(data["issued_date"])
    if "expiration_date" in data:
        entry.expiration_date = _date(data["expiration_date"])
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


def expiring_within(days: int, today: date | None = None) -> list[BoardCertification]:
    today = today or date.today()
    cutoff = today + timedelta(days=max(0, int(days)))
    return list(
        BoardCertification.objects.filter(
            expiration_date__isnull=False,
            expiration_date__lte=cutoff,
        ).order_by("expiration_date")
    )


def status(entry: BoardCertification, today: date | None = None, warning_days: int = 90) -> str:
    """Return one of: "expired", "expiring_soon", "current", "unknown"."""
    if entry.expiration_date is None:
        return "unknown"
    today = today or date.today()
    if entry.expiration_date < today:
        return "expired"
    if (entry.expiration_date - today).days <= warning_days:
        return "expiring_soon"
    return "current"


def serialize(entry: BoardCertification, today: date | None = None) -> dict:
    today = today or date.today()
    days_until = None
    if entry.expiration_date is not None:
        days_until = (entry.expiration_date - today).days
    return {
        "id": entry.dbid,
        "board_name": entry.board_name,
        "specialty": entry.specialty,
        "certification_number": entry.certification_number,
        "issued_date": entry.issued_date.isoformat() if entry.issued_date else None,
        "expiration_date": entry.expiration_date.isoformat() if entry.expiration_date else None,
        "days_until_expiration": days_until,
        "status": status(entry, today=today),
        "notes": entry.notes,
    }


def _s(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None
