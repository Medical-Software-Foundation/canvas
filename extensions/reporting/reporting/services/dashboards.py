"""CRUD + visibility logic for dashboards. Thin wrapper over Dashboard.objects."""

from django.db.models import Q

from reporting.models.dashboard import Dashboard


def serialize_summary(row) -> dict:
    widgets = (row.layout or {}).get("widgets", []) if isinstance(row.layout, dict) else []
    return {
        "id": row.dbid,
        "name": row.name,
        "visibility": row.visibility,
        "owner_id": row.owner_id,
        "widget_count": len(widgets),
    }


def serialize_detail(row) -> dict:
    out = serialize_summary(row)
    out["layout"] = row.layout
    out["default_period"] = row.default_period
    return out


def list_visible(staff_dbid: int):
    return Dashboard.objects.filter(
        Q(owner_id=staff_dbid) | Q(visibility="shared")
    ).order_by("-updated_at")


def get_visible(dashboard_id: int, staff_dbid: int):
    return (
        Dashboard.objects.filter(dbid=dashboard_id)
        .filter(Q(owner_id=staff_dbid) | Q(visibility="shared"))
        .first()
    )


def create(staff_dbid: int, name: str, visibility: str, layout: dict,
           default_period: dict):
    return Dashboard.objects.create(
        owner_id=staff_dbid,
        name=name,
        visibility=visibility if visibility in ("private", "shared") else "private",
        layout=layout,
        default_period=default_period,
        version=1,
    )


def update(dashboard_id: int, staff_dbid: int, expected_version: int,
           fields: dict) -> bool:
    rows = Dashboard.objects.filter(
        dbid=dashboard_id, owner_id=staff_dbid, version=expected_version
    ).update(version=expected_version + 1, **fields)
    return rows == 1


def delete(dashboard_id: int, staff_dbid: int) -> bool:
    deleted, _ = Dashboard.objects.filter(dbid=dashboard_id, owner_id=staff_dbid).delete()
    return deleted >= 1
