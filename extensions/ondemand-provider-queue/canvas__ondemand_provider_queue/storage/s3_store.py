"""Optional backend: the whole queue as one JSON document in the practice's S3 bucket.

Kept for practices that already run the queue on S3. Off unless
``QUEUE_STORAGE`` is ``s3``. Because the queue is one document, two changes
made at the same moment can overwrite each other (last write wins). The
default Canvas backend does not have this problem.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from canvas_sdk.clients.aws import S3, Credentials

from canvas__ondemand_provider_queue.storage.base import QueueEntry, QueueStore, Where, plain


class StoreUnavailableError(Exception):
    """Raised when the queue storage can't be read or written."""


class S3QueueStore(QueueStore):
    """Queue entries in one S3 object, read and rewritten on every change."""

    def __init__(self, client: S3, object_key: str) -> None:
        """Wrap an SDK S3 client and the object key holding the queue."""
        self.client = client
        self.object_key = object_key

    @classmethod
    def from_settings(
        cls, key: str, secret: str, region: str, bucket: str, object_key: str
    ) -> S3QueueStore:
        """Build the store from plugin settings."""
        client = S3(Credentials(key=key, secret=secret, region=region, bucket=bucket))
        if not client.is_ready():
            raise StoreUnavailableError("S3 storage is selected but not configured")
        return cls(client, object_key)

    def _load(self) -> dict[str, dict[str, Any]]:
        response = self.client.access_s3_object(self.object_key)
        if response is None:
            raise StoreUnavailableError("S3 storage is not configured")
        if response.status_code == HTTPStatus.NOT_FOUND:
            return {}
        if response.status_code != HTTPStatus.OK:
            # Never treat a failed read as an empty queue: the next save would wipe it.
            raise StoreUnavailableError(f"S3 read returned {response.status_code}")
        try:
            document = json.loads(response.text)
        except ValueError as exc:
            raise StoreUnavailableError("S3 queue document is not valid JSON") from exc
        entries = document.get("entries", {}) if isinstance(document, dict) else None
        if not isinstance(entries, dict):
            # Same rule as a failed read: never present a damaged document as an empty queue.
            raise StoreUnavailableError("S3 queue document has an unexpected shape")
        return entries

    def _save(self, entries: dict[str, dict[str, Any]]) -> None:
        response = self.client.upload_text_to_s3(self.object_key, json.dumps({"entries": entries}))
        if response is None or response.status_code not in (HTTPStatus.OK, HTTPStatus.CREATED):
            status = response.status_code if response is not None else "none"
            raise StoreUnavailableError(f"S3 write returned {status}")

    def _insert(self, entry: QueueEntry) -> None:
        entries = self._load()
        entries[entry.id] = entry.to_dict()
        self._save(entries)

    def _get(self, entry_id: str) -> QueueEntry | None:
        row = self._load().get(entry_id)
        return QueueEntry.from_dict(row) if row else None

    def _get_by_external_id(self, external_id: str) -> QueueEntry | None:
        for row in self._load().values():
            if row.get("external_id") == external_id:
                return QueueEntry.from_dict(row)
        return None

    def _find(self, where: Where) -> list[QueueEntry]:
        rows = [QueueEntry.from_dict(r) for r in self._load().values() if where.matches(r)]
        return sorted(rows, key=lambda e: e.created_at)

    def _update_if(self, entry_id: str | None, where: Where, changes: dict[str, Any]) -> str | None:
        entries = self._load()
        if entry_id is None:
            matches = sorted(
                (r for r in entries.values() if where.matches(r)),
                key=lambda r: r.get("created_at", ""),
            )
            if not matches:
                return None
            entry_id = matches[0]["id"]
        row = entries.get(entry_id)
        if row is None or not where.matches(row):
            return None
        row.update({k: plain(v) for k, v in changes.items()})
        self._save(entries)
        return entry_id

    def _delete_where(self, where: Where) -> int:
        entries = self._load()
        keep = {k: v for k, v in entries.items() if not where.matches(v)}
        removed = len(entries) - len(keep)
        if removed:
            self._save(keep)
        return removed
