"""Default backend: one Canvas custom data row per queue entry."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Q

from canvas__ondemand_provider_queue.models import QueueEntryRecord
from canvas__ondemand_provider_queue.storage.base import (
    ENTRY_FIELDS,
    QueueEntry,
    QueueStore,
    Where,
    plain,
)

# Entry field name -> model field name (the model's own primary key is dbid).
_FIELD_MAP = {"id": "entry_id"}


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _to_entry(record: QueueEntryRecord) -> QueueEntry:
    return QueueEntry.from_dict(
        {name: _iso(getattr(record, _FIELD_MAP.get(name, name))) for name in ENTRY_FIELDS}
    )


def _filter(where: Where) -> Q:
    q = Q()
    if where.status_in:
        q &= Q(status__in=[plain(s) for s in where.status_in])
    if where.unassigned:
        q &= Q(assigned_provider_id__isnull=True) | Q(assigned_provider_id="")
    if where.no_note:
        q &= Q(note_id__isnull=True) | Q(note_id="")
    if where.note_id is not None:
        q &= Q(note_id=where.note_id)
    if where.patient_id is not None:
        q &= Q(patient_id=where.patient_id)
    return q


class CanvasQueueStore(QueueStore):
    """Queue entries as ``QueueEntryRecord`` rows in the plugin's namespace.

    Every state change is a single ``UPDATE ... WHERE <expected state>``, so it
    is atomic: concurrent requests cannot overwrite each other's changes.
    """

    def _rows(self) -> Any:
        return QueueEntryRecord.objects.all()

    def _insert(self, entry: QueueEntry) -> None:
        data = entry.to_dict()
        values = {_FIELD_MAP.get(k, k): v for k, v in data.items()}
        values["created_at"] = datetime.fromisoformat(data["created_at"])
        values["updated_at"] = datetime.fromisoformat(data["updated_at"])
        QueueEntryRecord.objects.create(**values)

    def _get(self, entry_id: str) -> QueueEntry | None:
        record = self._rows().filter(entry_id=entry_id).first()
        return _to_entry(record) if record else None

    def _get_by_external_id(self, external_id: str) -> QueueEntry | None:
        record = self._rows().filter(external_id=external_id).first()
        return _to_entry(record) if record else None

    def _find(self, where: Where) -> list[QueueEntry]:
        return [_to_entry(r) for r in self._rows().filter(_filter(where)).order_by("created_at")]

    def _update_if(self, entry_id: str | None, where: Where, changes: dict[str, Any]) -> str | None:
        values = {k: plain(v) for k, v in changes.items()}
        if "updated_at" in values:
            values["updated_at"] = datetime.fromisoformat(values["updated_at"])
        if entry_id is None:
            target = (
                self._rows()
                .filter(_filter(where))
                .order_by("created_at")
                .values_list("entry_id", flat=True)
                .first()
            )
            if target is None:
                return None
            entry_id = target
        updated = self._rows().filter(_filter(where), entry_id=entry_id).update(**values)
        return entry_id if updated else None

    def _delete_where(self, where: Where) -> int:
        deleted, _ = self._rows().filter(_filter(where)).delete()
        return deleted
