"""Queue store behaviour on both backends: lifecycle, races, idempotency."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.db import IntegrityError, transaction

from canvas__ondemand_provider_queue.models import QueueEntryRecord
from canvas__ondemand_provider_queue.settings import Settings
from canvas__ondemand_provider_queue.storage import get_store
from canvas__ondemand_provider_queue.storage.base import (
    QueueEntry,
    QueueEntryStatus,
    QueueStore,
    Where,
    plain,
)
from canvas__ondemand_provider_queue.storage.canvas_store import CanvasQueueStore
from canvas__ondemand_provider_queue.storage.s3_store import S3QueueStore, StoreUnavailableError


class FakeS3:
    """Stands in for the SDK S3 client, keeping one object in memory."""

    def __init__(self, status: int = HTTPStatus.NOT_FOUND, body: str = "") -> None:
        self.status = status
        self.body = body
        self.ready = True
        self.write_status = HTTPStatus.OK
        self.writes = 0

    def is_ready(self) -> bool:
        return self.ready

    def access_s3_object(self, key: str) -> Any:
        if not self.ready:
            return None
        return MagicMock(status_code=self.status, text=self.body)

    def upload_text_to_s3(self, key: str, text: str) -> Any:
        if not self.ready:
            return None
        if self.write_status == HTTPStatus.OK:
            self.body, self.status = text, HTTPStatus.OK
        self.writes += 1
        return MagicMock(status_code=self.write_status)


def make_s3() -> S3QueueStore:
    return S3QueueStore(FakeS3(), "queue.json")  # type: ignore[arg-type]


@pytest.fixture(params=["canvas", "s3"])
def store(request: pytest.FixtureRequest) -> QueueStore:
    return CanvasQueueStore() if request.param == "canvas" else make_s3()


def test_full_lifecycle(store: QueueStore) -> None:
    entry, created = store.create_entry("pat-1", "Follow-up", practice_location_id="loc-1")
    assert created and entry.status == "awaiting_assignment"

    claimed, error = store.claim_entry(entry.id, "staff-1", "Dr A")
    assert error is None and claimed is not None
    assert claimed.status == "waiting_for_provider" and claimed.assigned_provider_id == "staff-1"

    started, error = store.start_entry(entry.id, "note-1")
    assert error is None and started is not None
    assert (started.status, started.note_id) == ("in_progress", "note-1")

    paused, _ = store.pause_entry(entry.id)
    assert paused is not None and paused.status == "paused"
    resumed, _ = store.resume_entry(entry.id)
    assert resumed is not None and resumed.status == "in_progress"

    done = store.complete_for_note("note-1", "pat-1")
    assert done is not None and done.status == "complete"
    assert store.list_entries(("complete",))[0].id == entry.id
    assert store.list_entries(("in_progress",)) == []


def test_second_claim_is_refused(store: QueueStore) -> None:
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "staff-1", "Dr A")
    taken, error = store.claim_entry(entry.id, "staff-2", "Dr B")
    assert taken is None and error == "Entry already claimed"
    assert store.get_entry(entry.id).assigned_provider_id == "staff-1"  # type: ignore[union-attr]


def test_same_provider_claiming_twice_is_a_no_op(store: QueueStore) -> None:
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "staff-1", "Dr A")
    again, error = store.claim_entry(entry.id, "staff-1", "Dr A")
    assert error is None and again is not None and again.assigned_provider_id == "staff-1"


def test_unknown_entry(store: QueueStore) -> None:
    assert store.claim_entry("missing", "s", "n") == (None, "Entry not found")
    assert store.pause_entry("missing") == (None, "Entry not found")


def test_repeated_external_id_returns_first_entry(store: QueueStore) -> None:
    first, created = store.create_entry("pat-1", "Follow-up", external_id="req-1")
    second, created_again = store.create_entry("pat-1", "Follow-up", external_id="req-1")
    assert created and not created_again and second.id == first.id
    assert len(store.list_entries(("awaiting_assignment",))) == 1


def test_start_twice_keeps_first_note(store: QueueStore) -> None:
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "staff-1", "Dr A")
    store.start_entry(entry.id, "note-1")
    again, error = store.start_entry(entry.id, "note-2")
    assert again is None and error == "Visit cannot be started from its current status"
    assert store.get_entry(entry.id).note_id == "note-1"  # type: ignore[union-attr]


def test_release_only_before_start(store: QueueStore) -> None:
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "staff-1", "Dr A")
    released, _ = store.release_entry(entry.id)
    assert released is not None and released.assigned_provider_id is None
    assert released.status == "awaiting_assignment"
    store.claim_entry(entry.id, "staff-1", "Dr A")
    store.start_entry(entry.id, "note-1")
    assert store.release_entry(entry.id)[1] == "Can only unassign a visit that has not started"


def test_pause_and_resume_need_the_right_state(store: QueueStore) -> None:
    entry, _ = store.create_entry("pat-1", "Follow-up")
    assert store.pause_entry(entry.id)[1] == "Can only pause an in-progress visit"
    assert store.resume_entry(entry.id)[1] == "Can only resume a paused visit"


def test_complete_falls_back_to_patient_entry_without_note(store: QueueStore) -> None:
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store._update_if(entry.id, Where(), {"status": QueueEntryStatus.IN_PROGRESS})
    done = store.complete_for_note("note-9", "pat-1")
    assert done is not None and done.id == entry.id and done.note_id == "note-9"


def test_complete_ignores_unrelated_note(store: QueueStore) -> None:
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "staff-1", "Dr A")
    store.start_entry(entry.id, "note-1")
    assert store.complete_for_note("note-other", "pat-1") is None
    assert store.complete_for_note("note-other", None) is None
    assert store.get_entry(entry.id).status == "in_progress"  # type: ignore[union-attr]


def test_list_filters_and_clear(store: QueueStore) -> None:
    store.create_entry("pat-1", "A", priority="urgent", practice_location_id="loc-1")
    store.create_entry("pat-2", "B", practice_location_id="loc-2")
    active = ("awaiting_assignment",)
    assert [e.patient_id for e in store.list_entries(active)] == ["pat-1", "pat-2"]
    assert [e.patient_id for e in store.list_entries(active, practice_location_id="loc-2")] == [
        "pat-2"
    ]
    assert [e.patient_id for e in store.list_entries(active, priority="urgent")] == ["pat-1"]
    assert store.clear_active() == 2
    assert store.list_entries(active) == []


def test_update_if_without_match_returns_none(store: QueueStore) -> None:
    assert store._update_if(None, Where(status_in=("paused",)), {"status": "complete"}) is None


def test_base_primitives_must_be_implemented() -> None:
    base = QueueStore()
    entry = QueueEntry(id="x", patient_id="p", reason_for_visit="r")
    calls = [
        lambda: base._insert(entry),
        lambda: base._get("x"),
        lambda: base._get_by_external_id("x"),
        lambda: base._find(Where()),
        lambda: base._update_if("x", Where(), {}),
        lambda: base._delete_where(Where()),
    ]
    for call in calls:
        with pytest.raises(NotImplementedError):
            call()


def test_where_matches_each_condition() -> None:
    row = {"status": "paused", "assigned_provider_id": "s", "note_id": "n", "patient_id": "p"}
    assert Where(status_in=("paused",), note_id="n", patient_id="p").matches(row)
    assert not Where(unassigned=True).matches(row)
    assert not Where(no_note=True).matches(row)
    assert not Where(note_id="other").matches(row)
    assert not Where(patient_id="other").matches(row)
    assert plain(QueueEntryStatus.PAUSED) == "paused"


def test_canvas_rows_are_unique_by_entry_and_external_id() -> None:
    store = CanvasQueueStore()
    entry, _ = store.create_entry("pat-1", "A", external_id="req-1")
    record = QueueEntryRecord.objects.get(entry_id=entry.id)
    with pytest.raises(IntegrityError), transaction.atomic():
        QueueEntryRecord.objects.create(
            entry_id="other",
            patient_id="pat-2",
            external_id="req-1",
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def test_s3_reads_existing_document_and_refuses_failed_reads() -> None:
    entry = QueueEntry(id="e1", patient_id="p", reason_for_visit="r", created_at="t")
    client = FakeS3(HTTPStatus.OK, json.dumps({"entries": {"e1": entry.to_dict()}}))
    store = S3QueueStore(client, "k")  # type: ignore[arg-type]
    assert store.get_entry("e1") is not None
    assert store._get_by_external_id("none") is None

    client.status = HTTPStatus.FORBIDDEN
    with pytest.raises(StoreUnavailableError):
        store.get_entry("e1")

    client.status = HTTPStatus.OK
    for damaged in ("{not json", "[]", json.dumps({"entries": [1]}), ""):
        client.body = damaged
        with pytest.raises(StoreUnavailableError):
            store.get_entry("e1")
        with pytest.raises(StoreUnavailableError):
            store.create_entry("p", "r")  # must not overwrite a damaged document
    assert client.writes == 0

    client.body = json.dumps({})
    assert store.get_entry("e1") is None


def test_s3_write_failures_raise() -> None:
    client = FakeS3()
    store = S3QueueStore(client, "k")  # type: ignore[arg-type]
    client.write_status = HTTPStatus.INTERNAL_SERVER_ERROR
    with pytest.raises(StoreUnavailableError):
        store.create_entry("p", "r")
    client.ready = False
    with pytest.raises(StoreUnavailableError):
        store.get_entry("x")
    client.ready, client.status = True, HTTPStatus.OK
    client.body = json.dumps({"entries": {}})
    client.ready = False
    with pytest.raises(StoreUnavailableError):
        store._save({})


def test_s3_clear_with_nothing_open_does_not_write() -> None:
    client = FakeS3()
    store = S3QueueStore(client, "k")  # type: ignore[arg-type]
    assert store.clear_active() == 0 and client.writes == 0


def test_get_store_picks_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(get_store(Settings.from_secrets({})), CanvasQueueStore)
    s3_settings = Settings.from_secrets({"QUEUE_STORAGE": "S3"})
    with pytest.raises(StoreUnavailableError):
        get_store(s3_settings)  # no keys: refuse instead of silently using an empty queue

    fake = FakeS3()
    monkeypatch.setattr(
        "canvas__ondemand_provider_queue.storage.s3_store.S3", lambda credentials: fake
    )
    store = get_store(s3_settings)
    assert isinstance(store, S3QueueStore) and store.object_key.endswith("queue.json")
