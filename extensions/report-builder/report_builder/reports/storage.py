"""Storage layer for saved reports — wraps the `SavedReport` CustomModel.

Callers work with `Report` dataclasses; this layer hides the database row.
A fresh `id` (uuid4) is minted on `save_report` when the report has none.
"""

import uuid
from dataclasses import dataclass, replace
from typing import Any

from report_builder.models import SavedReport
from report_builder.reports.models import Report, report_from_json, report_to_json


@dataclass(frozen=True)
class ReportMetadata:
    """Lightweight summary used by the list endpoint."""

    id: str
    name: str
    description: str
    root_entity: str
    created_by: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "root_entity": self.root_entity,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_metadata(row: SavedReport) -> ReportMetadata:
    return ReportMetadata(
        id=row.report_id,
        name=row.name,
        description=row.description,
        root_entity=row.root_entity,
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


def _row_to_report(row: SavedReport) -> Report:
    config: dict[str, Any] = dict(row.config or {})
    config.setdefault("name", row.name)
    config.setdefault("description", row.description)
    config.setdefault("root_entity", row.root_entity)
    config["id"] = row.report_id
    config["created_by"] = row.created_by
    config["created_at"] = row.created_at.isoformat() if row.created_at else ""
    config["updated_at"] = row.updated_at.isoformat() if row.updated_at else ""
    return report_from_json(config)


def list_reports() -> list[ReportMetadata]:
    """List all saved reports, most recently updated first."""
    rows = SavedReport.objects.only(
        "report_id",
        "name",
        "description",
        "root_entity",
        "created_by",
        "created_at",
        "updated_at",
    ).order_by("-updated_at")
    return [_row_to_metadata(r) for r in rows]


def get_report(report_id: str) -> Report | None:
    """Return the report with `report_id`, or None if it doesn't exist."""
    row = SavedReport.objects.filter(report_id=report_id).first()
    if row is None:
        return None
    return _row_to_report(row)


def save_report(report: Report, created_by: str) -> Report:
    """Create a new saved report. Returns the persisted Report with id assigned."""
    new_id = report.id or str(uuid.uuid4())
    report = replace(report, id=new_id, created_by=created_by or report.created_by)

    config_payload = report_to_json(report)
    row = SavedReport.objects.create(
        report_id=new_id,
        name=report.name,
        description=report.description,
        root_entity=report.root_entity,
        config=config_payload,
        created_by=report.created_by,
    )
    return _row_to_report(row)


def update_report(report: Report) -> Report | None:
    """Update an existing report. Returns None if the report doesn't exist."""
    if not report.id:
        raise ValueError("update_report requires report.id")

    row = SavedReport.objects.filter(report_id=report.id).first()
    if row is None:
        return None

    config_payload = report_to_json(report)
    row.name = report.name
    row.description = report.description
    row.root_entity = report.root_entity
    row.config = config_payload
    row.save()
    return _row_to_report(row)


def delete_report(report_id: str) -> bool:
    """Delete a report by id. Returns True if a row was deleted."""
    deleted, _ = SavedReport.objects.filter(report_id=report_id).delete()
    return bool(deleted)
