"""CRUD + visibility logic for saved reports. Thin wrapper over Report.objects."""

from django.db.models import Q

from reporting.models.report import Report


def serialize_summary(row) -> dict:
    return {
        "id": row.dbid,
        "name": row.name,
        "category": row.category,
        "visibility": row.visibility,
        "owner_id": row.owner_id,
    }


def serialize_detail(row) -> dict:
    out = serialize_summary(row)
    out["definition"] = row.definition
    return out


def list_visible(staff_dbid: int):
    """Reports owned by the staff member OR shared with the org."""
    return Report.objects.filter(
        Q(owner_id=staff_dbid) | Q(visibility="shared")
    ).order_by("-updated_at")


def get_visible(report_id: int, staff_dbid: int):
    return (
        Report.objects.filter(dbid=report_id)
        .filter(Q(owner_id=staff_dbid) | Q(visibility="shared"))
        .first()
    )


def create(staff_dbid: int, name: str, category: str, visibility: str,
           definition: dict):
    return Report.objects.create(
        owner_id=staff_dbid,
        name=name,
        category=category,
        visibility=visibility if visibility in ("private", "shared") else "private",
        definition=definition,
        version=1,
    )


def update(report_id: int, staff_dbid: int, expected_version: int,
           fields: dict) -> bool:
    """Owner-only, optimistic-locked update. Returns False on conflict/not-owner."""
    rows = Report.objects.filter(
        dbid=report_id, owner_id=staff_dbid, version=expected_version
    ).update(version=expected_version + 1, **fields)
    return rows == 1


def delete(report_id: int, staff_dbid: int) -> bool:
    deleted, _ = Report.objects.filter(dbid=report_id, owner_id=staff_dbid).delete()
    return deleted >= 1
