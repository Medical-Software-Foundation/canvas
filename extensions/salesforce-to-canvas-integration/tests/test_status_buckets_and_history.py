"""Tests for the Records bucketing and the Activity ledger endpoint.

The Records screen splits the live rows into needs action and skipped, the two
buckets that still carry an action. Applied events leave the screen and land in
the Activity ledger, which joins each decision with its event so it carries the
Received and Applied columns. The bucketing is exercised through the
``_bucket_records`` helper because the query that feeds it uses Postgres only
features the SQLite test database cannot run, the same reason ``_record_view`` is
tested directly. The activity endpoint uses a plain ordered slice, so it is
driven through the route method. See journal cnv-909/091 and 104.
"""

from __future__ import annotations

import json
from base64 import b64decode
from typing import Any
from unittest.mock import MagicMock

import factory

import pytest

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from salesforce_to_canvas_integration.handlers import status_api
from salesforce_to_canvas_integration.handlers.status_api import (
    _ACTIVITY_LIMIT,
    SalesforceStatusAPI,
    _bucket_records,
    _skip_decision_by_event_id,
)
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.resolution_audit_entry import (
    ResolutionAuditEntry,
)
from salesforce_to_canvas_integration.services.config import DEFAULT_FIELD_MAPPING
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)


def _seed_linked_patient(external_id: str) -> Any:
    """Link a Canvas patient to a Salesforce id through the external identifier."""
    from datetime import date, timedelta

    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system=SALESFORCE_IDENTIFIER_SYSTEM,
        value=external_id,
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )
    return patient


class RowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured row, defaulting to a pending create."""

    class Meta:
        model = IncomingPatientRecord

    external_id = factory.Sequence(lambda n: f"00Q{n:08d}")
    source_object = "Contact"
    action = "create"
    first_name = "Ada"
    last_name = "Lovelace"
    email = "ada@example.com"
    phone = "+15551112222"
    raw_payload = factory.LazyAttribute(lambda o: {"Id": o.external_id})
    content_hash = factory.Sequence(lambda n: f"hash-{n}")
    status = "new"


class HistoryEntryFactory(factory.django.DjangoModelFactory[ResolutionAuditEntry]):
    """A decision log entry."""

    class Meta:
        model = ResolutionAuditEntry

    external_id = factory.Sequence(lambda n: f"00Q{n:08d}")
    event_id = factory.Sequence(lambda n: n + 1)
    action = "create"
    action_taken = "created"
    staff_key = "deadbeefdeadbeefdeadbeefdeadbeef"
    staff_name = "Grace Hopper"


@pytest.fixture(autouse=True)
def _stub_token_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the token cache so the activity route runs outside a plugin context.

    The activity route now reads the stored Salesforce instance url for the
    record link through ``TokenStore(get_cache())``, the same call the synced
    route makes, and ``get_cache`` demands a plugin runtime the unit harness does
    not provide. With no tokens the instance url is empty and the Salesforce link
    is empty, which the default tests do not assert on. A test that needs a link
    overrides this with its own token stub. See journal cnv-928/030.
    """

    class _NoTokens:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def load(self) -> None:
            return None

    monkeypatch.setattr(status_api, "get_cache", lambda: None)
    monkeypatch.setattr(status_api, "TokenStore", _NoTokens)


def _make_api(query: dict[str, str] | None = None) -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = {}
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    handler.request = MagicMock()
    handler.request.query_params = query or {}
    return handler


def _json_body(effect: Any) -> dict[str, Any]:
    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


def _seed_history(n: int) -> list[ResolutionAuditEntry]:
    """Create n decision rows with spread timestamps, oldest to newest.

    ``created_at`` is set explicitly one minute apart so the newest first order
    is deterministic for the pagination tests, since the factory default would
    stamp every row at the same instant.
    """
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = HistoryEntryFactory.create_batch(n)
    for i, row in enumerate(rows):
        ResolutionAuditEntry.objects.filter(dbid=row.dbid).update(
            created_at=base + timedelta(minutes=i)
        )
    return rows


# ---------------------------------------------------------------------------
# bucketing
# ---------------------------------------------------------------------------


def test_bucket_records_splits_into_needs_action_and_skipped() -> None:
    """A new row is needs action, a dismissed row is skipped, applied is gone."""
    new_row = RowFactory.create(external_id="00QNEW", status="new")
    RowFactory.create(external_id="00QACC", status="accepted")
    dismissed = RowFactory.create(external_id="00QDIS", status="dismissed")

    pending, skipped = _bucket_records(
        [new_row, dismissed], DEFAULT_FIELD_MAPPING
    )

    assert [r["external_id"] for r in pending] == ["00QNEW"]
    assert [r["external_id"] for r in skipped] == ["00QDIS"]


def test_bucket_records_drops_applied_events_from_the_records_screen() -> None:
    """Accepted events never ride the Records screen, they live in Activity.

    The Records screen is the actionable surface, and an applied event has no
    action left. See journal cnv-909/104.
    """
    new_row = RowFactory.create(external_id="00QNEW", status="new")
    accepted = RowFactory.create(external_id="00QACC", status="accepted")
    dismissed = RowFactory.create(external_id="00QDIS", status="dismissed")

    pending, skipped = _bucket_records(
        [new_row, accepted, dismissed], DEFAULT_FIELD_MAPPING
    )

    external_ids = [r["external_id"] for r in pending + skipped]
    assert "00QACC" not in external_ids


def test_bucket_records_orders_each_bucket_newest_first() -> None:
    """Within a bucket the newest received row sorts to the front."""
    from datetime import UTC, datetime

    older = RowFactory.create(external_id="00QOLD", status="dismissed")
    newer = RowFactory.create(external_id="00QNEWER", status="dismissed")
    IncomingPatientRecord.objects.filter(dbid=older.dbid).update(
        received_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    IncomingPatientRecord.objects.filter(dbid=newer.dbid).update(
        received_at=datetime(2026, 2, 1, tzinfo=UTC)
    )
    older.refresh_from_db()
    newer.refresh_from_db()

    _pending, skipped = _bucket_records([older, newer], DEFAULT_FIELD_MAPPING)

    assert [r["external_id"] for r in skipped] == ["00QNEWER", "00QOLD"]


def test_bucket_records_empty_input_yields_two_empty_lists() -> None:
    """No rows yields two empty buckets, never a missing one."""
    pending, skipped = _bucket_records([], DEFAULT_FIELD_MAPPING)

    assert pending == []
    assert skipped == []


def test_bucket_records_keeps_skipped_create_and_pending_modify_separate() -> None:
    """A skipped create and a newer pending modify for one record stay separate.

    The per event queue headline. Story four stops the older skipped event from
    hiding behind the newest event, so the create sits in skipped while the
    modify sits in needs action, both live. See journal cnv-909/092 story four.
    """
    create = RowFactory.create(
        external_id="00QSPLIT", action="create", status="dismissed", content_hash="h1"
    )
    modify = RowFactory.create(
        external_id="00QSPLIT", action="modify", status="new", content_hash="h2"
    )

    pending, skipped = _bucket_records([create, modify], DEFAULT_FIELD_MAPPING)

    assert [r["event_id"] for r in pending] == [modify.pk]
    assert [r["event_id"] for r in skipped] == [create.pk]


def test_bucket_records_attaches_gap_to_pending_rows() -> None:
    """With the gap inputs, each pending row carries its gap object.

    Story six. A skipped create behind a pending modify for one record makes the
    modify's gap read one skipped creation, with the skipping operator named for
    the tooltip. See journal cnv-909/092 story six.
    """
    from datetime import UTC, datetime

    create = RowFactory.create(
        external_id="00QGAPB", action="create", status="dismissed", content_hash="gb1"
    )
    modify = RowFactory.create(
        external_id="00QGAPB", action="modify", status="new", content_hash="gb2"
    )
    IncomingPatientRecord.objects.filter(dbid=create.dbid).update(
        received_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    IncomingPatientRecord.objects.filter(dbid=modify.dbid).update(
        received_at=datetime(2026, 2, 1, tzinfo=UTC)
    )
    create.refresh_from_db()
    modify.refresh_from_db()

    pending, _skipped = _bucket_records(
        [create, modify],
        DEFAULT_FIELD_MAPPING,
        set(),
        {create.pk: "Grace Hopper"},
    )

    assert len(pending) == 1
    gap = pending[0]["gap"]
    assert gap["count"] == 1
    assert gap["has_anchor"] is False
    assert gap["events"][0]["event_id"] == create.pk
    assert gap["events"][0]["who"] == "Grace Hopper"


def test_bucket_records_omits_gap_without_inputs() -> None:
    """The pre story six two argument call attaches no gap object."""
    new_row = RowFactory.create(external_id="00QNOGAP", status="new")

    pending, _skipped = _bucket_records([new_row], DEFAULT_FIELD_MAPPING)

    assert "gap" not in pending[0]


def test_bucket_records_keeps_only_the_newest_pending_row() -> None:
    """Records collapses each contact to one row, the newest pending event.

    Two pending syncs for one contact leave only the newest in the bucket. The
    older one is suppressed, it rides in the newest row's overridden history
    rather than appearing as a second row. The surfaced row is always actionable.
    See journal cnv-938/022.
    """
    from datetime import UTC, datetime

    older = RowFactory.create(external_id="00QNEWEST", content_hash="n1")
    newer = RowFactory.create(external_id="00QNEWEST", content_hash="n2")
    IncomingPatientRecord.objects.filter(dbid=older.dbid).update(
        received_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    IncomingPatientRecord.objects.filter(dbid=newer.dbid).update(
        received_at=datetime(2026, 2, 1, tzinfo=UTC)
    )
    older.refresh_from_db()
    newer.refresh_from_db()

    pending, _skipped = _bucket_records([older, newer], DEFAULT_FIELD_MAPPING)

    assert len(pending) == 1
    assert pending[0]["event_id"] == newer.pk
    assert pending[0]["actionable"] is True
    assert pending[0]["supersede_reason"] == ""


def test_bucket_records_serializes_the_sync_and_delete_event() -> None:
    """Every surfaced row carries its Salesforce event, Sync or Delete.

    A create or modify arrival is a Sync, a delete arrival is a Delete, the two
    events the rep set on the Canvas Sync field. The delete needs a linked patient
    to surface at all. See journal cnv-938/017 018 022.
    """
    sync_row = RowFactory.create(external_id="00QSYNC", action="create")
    _seed_linked_patient("00QDEL")
    delete_row = RowFactory.create(external_id="00QDEL", action="delete")

    pending, _skipped = _bucket_records(
        [sync_row, delete_row], DEFAULT_FIELD_MAPPING
    )

    by_id = {row["event_id"]: row for row in pending}
    assert by_id[sync_row.pk]["event"] == "Sync"
    assert by_id[delete_row.pk]["event"] == "Delete"


def test_bucket_records_rows_carry_salesforce_url_and_patient_id() -> None:
    """Every surfaced row carries the Salesforce link and the live patient id.

    The expanded row's links bar opens both, so the serializer builds the
    Lightning record url from the instance url and threads the linked Canvas
    patient id, empty on an unlinked row. With no instance url the link falls
    to an empty string. See journal cnv-941/012.
    """
    patient = _seed_linked_patient("00QLNK")
    linked_row = RowFactory.create(external_id="00QLNK", action="modify")
    unlinked_row = RowFactory.create(external_id="00QUNL", action="create")
    skipped_row = RowFactory.create(external_id="00QSKP", status="dismissed")

    pending, skipped = _bucket_records(
        [linked_row, unlinked_row, skipped_row],
        DEFAULT_FIELD_MAPPING,
        instance_url="https://example.my.salesforce.com",
    )

    by_id = {row["external_id"]: row for row in pending + skipped}
    assert by_id["00QLNK"]["salesforce_url"] == (
        "https://example.my.salesforce.com/lightning/r/Contact/00QLNK/view"
    )
    assert by_id["00QLNK"]["patient_id"] == str(patient.id)
    assert by_id["00QUNL"]["patient_id"] == ""
    assert by_id["00QSKP"]["salesforce_url"] == (
        "https://example.my.salesforce.com/lightning/r/Contact/00QSKP/view"
    )

    # Without an instance url the link is empty and the client renders no link.
    pending, _skipped = _bucket_records([unlinked_row], DEFAULT_FIELD_MAPPING)
    assert pending[0]["salesforce_url"] == ""


def test_bucket_records_delete_without_a_patient_drops_off_records() -> None:
    """A newest delete with no Canvas patient has nothing to delete, so it drops.

    The arrival still lives in the Activity ledger, it just leaves the Records
    surface rather than sitting there as an inert row. See journal cnv-938/022.
    """
    delete_row = RowFactory.create(external_id="00QDELNOPT", action="delete")

    pending, _skipped = _bucket_records([delete_row], DEFAULT_FIELD_MAPPING)

    assert pending == []


def test_skipped_record_view_carries_the_latest_skip_reason() -> None:
    """A skipped row in the bucket carries the skip reason, skipper, and time.

    The skip decision map threads through to the skipped branch of the record
    view. Pending rows never carry a reason. See journal cnv-928/012.
    """
    skipped_row = RowFactory.create(external_id="00QSKIP", status="dismissed")
    HistoryEntryFactory.create(
        external_id="00QSKIP",
        event_id=skipped_row.pk,
        action_taken="skipped",
        staff_name="Grace Hopper",
        note="duplicate lead",
    )

    decision = _skip_decision_by_event_id()
    _pending, skipped = _bucket_records(
        [skipped_row], DEFAULT_FIELD_MAPPING, set(), {}, decision
    )

    assert len(skipped) == 1
    assert skipped[0]["skip_reason"] == "duplicate lead"
    assert skipped[0]["skipped_by"] == "Grace Hopper"
    assert skipped[0]["skipped_at"] is not None


def test_skip_decision_map_keeps_the_latest_of_two_skips() -> None:
    """When an event is skipped, reopened, and skipped again the latest wins.

    The map is ordered oldest first so the most recent skip note survives, the
    same idiom as the skip actor map. See journal cnv-928/012.
    """
    from datetime import UTC, datetime, timedelta

    skipped_row = RowFactory.create(external_id="00QTWICE", status="dismissed")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    first = HistoryEntryFactory.create(
        external_id="00QTWICE",
        event_id=skipped_row.pk,
        action_taken="skipped",
        staff_name="Ada Lovelace",
        note="first reason",
    )
    second = HistoryEntryFactory.create(
        external_id="00QTWICE",
        event_id=skipped_row.pk,
        action_taken="skipped",
        staff_name="Grace Hopper",
        note="second reason",
    )
    ResolutionAuditEntry.objects.filter(dbid=first.dbid).update(created_at=base)
    ResolutionAuditEntry.objects.filter(dbid=second.dbid).update(
        created_at=base + timedelta(minutes=5)
    )

    decision = _skip_decision_by_event_id()

    assert decision[skipped_row.pk]["note"] == "second reason"
    assert decision[skipped_row.pk]["staff_name"] == "Grace Hopper"


def test_pending_record_view_carries_no_skip_reason() -> None:
    """A pending row passes None for the skip decision and stays untouched.

    See journal cnv-928/012.
    """
    new_row = RowFactory.create(external_id="00QPEND", status="new")

    pending, _skipped = _bucket_records([new_row], DEFAULT_FIELD_MAPPING)

    assert pending[0]["skip_reason"] == ""
    assert pending[0]["skipped_by"] == ""
    assert pending[0]["skipped_at"] is None


# ---------------------------------------------------------------------------
# activity ledger endpoint
# ---------------------------------------------------------------------------


def _drive_activity(api: SalesforceStatusAPI) -> dict[str, Any]:
    return _json_body(api.activity()[0])


def test_activity_returns_entries_newest_action_first() -> None:
    """The activity endpoint serves the decision log ordered newest action first."""
    from datetime import UTC, datetime

    older = HistoryEntryFactory.create(external_id="00QHIST", action_taken="created")
    newer = HistoryEntryFactory.create(
        external_id="00QHIST", action="modify", action_taken="modify_applied"
    )
    ResolutionAuditEntry.objects.filter(dbid=older.dbid).update(
        created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    ResolutionAuditEntry.objects.filter(dbid=newer.dbid).update(
        created_at=datetime(2026, 2, 1, tzinfo=UTC)
    )

    body = _drive_activity(_make_api())

    assert [e["action_taken"] for e in body["entries"]] == [
        "modify_applied",
        "created",
    ]
    first = body["entries"][0]
    assert first["external_id"] == "00QHIST"
    assert first["staff_name"] == "Grace Hopper"
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["limit"] == _ACTIVITY_LIMIT


def test_activity_joins_received_and_applied_from_the_event() -> None:
    """A demographic apply carries Received from the payload and Applied written.

    The decision links to its event, the activity view maps the immutable payload
    for the Received column and reads the resolved typed columns for the Applied
    column. A demographic writing resolution fills both. See journal cnv-909/104.
    """
    event = RowFactory.create(
        external_id="00QJOIN",
        action="modify",
        status="accepted",
        first_name="Mike",
        last_name="Smith",
        email="mike.old@example.com",
        raw_payload={"Id": "00QJOIN", "Email": "mike.old@example.com"},
    )
    HistoryEntryFactory.create(
        external_id="00QJOIN",
        event_id=event.pk,
        action="modify",
        action_taken="modify_applied",
    )

    body = _drive_activity(_make_api())

    entry = body["entries"][0]
    assert entry["applied"] is not None
    assert entry["applied"]["email"] == "mike.old@example.com"
    assert entry["received"] is not None


def test_activity_carries_canvas_before_only_for_an_applied_modify() -> None:
    """The feed item exposes the stored chart before snapshot for a modify apply.

    A modify apply stored the chart as it stood before the write, so the item
    carries it as the Was in Canvas column. A create has no prior chart, so its
    snapshot is empty and the item reports None. See journal cnv-928/037.
    """
    modify_event = RowFactory.create(
        external_id="00QBEFORE",
        action="modify",
        status="accepted",
        raw_payload={"Id": "00QBEFORE", "Email": "after@example.com"},
    )
    HistoryEntryFactory.create(
        external_id="00QBEFORE",
        event_id=modify_event.pk,
        action="modify",
        action_taken="modify_applied",
        canvas_before={"first_name": "Mike", "last_name": "Before"},
    )
    create_event = RowFactory.create(
        external_id="00QFRESH",
        action="create",
        status="accepted",
        raw_payload={"Id": "00QFRESH", "Email": "new@example.com"},
    )
    HistoryEntryFactory.create(
        external_id="00QFRESH",
        event_id=create_event.pk,
        action="create",
        action_taken="created",
    )

    body = _drive_activity(_make_api())
    # Each event yields both an arrival line and a decision line, so pick the
    # decision entries, the ones carrying a resolution.
    decisions = {
        e["external_id"]: e
        for e in body["entries"]
        if e.get("action_taken")
    }

    assert decisions["00QBEFORE"]["canvas_before"] == {
        "first_name": "Mike",
        "last_name": "Before",
    }
    # A create wrote no prior chart, so the snapshot stays empty and reads None.
    assert decisions["00QFRESH"]["canvas_before"] is None


def test_activity_received_carries_the_full_demographic_set() -> None:
    """Received packs the full demographic set the Details comparison table shows.

    The comparison table lists Name, Date of birth, Sex at birth, Email, Phone,
    Mobile, and Address, so the feed item carries the mapped fields and telecom for
    all of them, not only name, email, and phone. See journal cnv-928/023.
    """
    event = RowFactory.create(
        external_id="00QFULL",
        action="create",
        status="accepted",
        first_name="Mike",
        last_name="Smith",
        email="mike@example.com",
        raw_payload={
            "Id": "00QFULL",
            "FirstName": "Mike",
            "LastName": "Smith",
            "Birthdate": "1990-01-02",
            "Gender": "male",
            "Email": "mike@example.com",
            "Phone": "+15551112222",
            "MobilePhone": "+15553334444",
            "MailingStreet": "1 A St",
            "MailingCity": "Boston",
            "MailingState": "MA",
        },
    )
    HistoryEntryFactory.create(
        external_id="00QFULL",
        event_id=event.pk,
        action="create",
        action_taken="created",
    )

    body = _drive_activity(_make_api())

    received = body["entries"][0]["received"]
    assert received["first_name"] == "Mike"
    assert received["last_name"] == "Smith"
    assert received["date_of_birth"] == "1990-01-02"
    assert received["sex_at_birth"] == "male"
    assert received["mobile"] == "+15553334444"
    assert received["address_line_1"] == "1 A St"
    assert received["city"] == "Boston"
    assert received["state"] == "MA"


def test_activity_leaves_applied_empty_for_a_skip() -> None:
    """A skip wrote no demographics, so its Applied column is empty."""
    event = RowFactory.create(
        external_id="00QSKIP", action="modify", status="dismissed"
    )
    HistoryEntryFactory.create(
        external_id="00QSKIP",
        event_id=event.pk,
        action="modify",
        action_taken="skipped",
    )

    body = _drive_activity(_make_api())

    entry = body["entries"][0]
    assert entry["applied"] is None
    assert entry["received"] is not None


def test_activity_is_empty_when_no_decisions() -> None:
    """No decision log rows yields an empty ledger with no next page."""
    body = _drive_activity(_make_api())

    assert body["entries"] == []
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_activity_first_page_caps_and_offers_a_cursor() -> None:
    """When more than a page exist, the endpoint caps and offers a next cursor."""
    _seed_history(_ACTIVITY_LIMIT + 5)

    body = _drive_activity(_make_api())

    assert len(body["entries"]) == _ACTIVITY_LIMIT
    assert body["has_more"] is True
    assert body["next_cursor"] is not None
    assert body["next_cursor"]["ts"] == body["entries"][-1]["ts"]
    assert body["next_cursor"]["kind"] == body["entries"][-1]["kind"]
    assert body["next_cursor"]["id"] == body["entries"][-1]["id"]


def test_activity_second_page_via_cursor_returns_remainder_without_overlap() -> None:
    """The cursor from page one fetches the rest, no repeat and no skip."""
    total = _ACTIVITY_LIMIT + 5
    _seed_history(total)

    first = _drive_activity(_make_api())
    cursor = first["next_cursor"]
    second = _drive_activity(
        _make_api(
            {
                "before": cursor["ts"],
                "before_kind": cursor["kind"],
                "before_id": str(cursor["id"]),
            }
        )
    )

    assert len(second["entries"]) == 5
    assert second["has_more"] is False
    assert second["next_cursor"] is None
    first_ids = [e["id"] for e in first["entries"]]
    second_ids = [e["id"] for e in second["entries"]]
    assert set(first_ids).isdisjoint(second_ids)
    assert len(set(first_ids) | set(second_ids)) == total


def test_activity_cursor_tiebreaks_on_dbid_when_created_at_ties() -> None:
    """Rows sharing a timestamp split on dbid, the boundary never repeats a row."""
    from datetime import UTC, datetime

    shared = datetime(2026, 1, 1, tzinfo=UTC)
    rows = HistoryEntryFactory.create_batch(5)
    for row in rows:
        ResolutionAuditEntry.objects.filter(dbid=row.dbid).update(created_at=shared)
    ids = sorted(row.dbid for row in rows)
    # Ask for rows older than the middle one at the shared timestamp. Only the
    # two with a smaller dbid qualify, returned newest dbid first.
    body = _drive_activity(
        _make_api({"before": shared.isoformat(), "before_id": str(ids[2])})
    )

    assert [e["id"] for e in body["entries"]] == [ids[1], ids[0]]


def test_activity_malformed_cursor_serves_the_first_page() -> None:
    """A garbage or partial cursor falls back to the newest page."""
    _seed_history(3)

    body = _drive_activity(
        _make_api({"before": "not-a-date", "before_id": "abc"})
    )

    assert len(body["entries"]) == 3
    assert body["has_more"] is False


def test_activity_includes_inbound_arrival_lines() -> None:
    """An inbound event with no decision still appears as an arrival line.

    The widened feed records every arrival, so a captured event that no operator
    has touched is visible in Activity with an arrived marker and the Received
    demographics. See journal cnv-928/014.
    """
    RowFactory.create(external_id="00QARR", first_name="Ada", last_name="Lovelace")

    body = _drive_activity(_make_api())

    arrivals = [e for e in body["entries"] if e["kind"] == "received"]
    assert len(arrivals) == 1
    assert arrivals[0]["external_id"] == "00QARR"
    assert arrivals[0]["action_taken"] == ""
    assert arrivals[0]["received"] is not None
    assert arrivals[0]["applied"] is None


def test_activity_merges_arrivals_and_decisions_in_time_order() -> None:
    """The feed interleaves both logs into one stream, newest first.

    A decision and an arrival sharing a timestamp order with the decision first,
    and across distinct timestamps the newest wins. See journal cnv-928/015.
    """
    from datetime import UTC, datetime

    a = RowFactory.create(external_id="00QA")
    IncomingPatientRecord.objects.filter(dbid=a.dbid).update(
        received_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    )
    b = HistoryEntryFactory.create(external_id="00QB", action_taken="created")
    ResolutionAuditEntry.objects.filter(dbid=b.dbid).update(
        created_at=datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    )
    c = RowFactory.create(external_id="00QC")
    IncomingPatientRecord.objects.filter(dbid=c.dbid).update(
        received_at=datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    )
    d = HistoryEntryFactory.create(external_id="00QD", action_taken="modify_applied")
    ResolutionAuditEntry.objects.filter(dbid=d.dbid).update(
        created_at=datetime(2026, 1, 1, 4, 0, tzinfo=UTC)
    )

    body = _drive_activity(_make_api())

    assert [(e["kind"], e["external_id"]) for e in body["entries"]] == [
        ("decision", "00QD"),
        ("received", "00QC"),
        ("decision", "00QB"),
        ("received", "00QA"),
    ]


def test_activity_cursor_pages_across_both_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keyset cursor pages the merged feed with no repeat or skip.

    With the page limit shrunk to two, the first page takes the two newest across
    both logs and the cursor fetches the remaining two from the other table
    without overlap. See journal cnv-928/015.
    """
    from datetime import UTC, datetime

    monkeypatch.setattr(status_api, "_ACTIVITY_LIMIT", 2)

    a = RowFactory.create(external_id="00QA")
    IncomingPatientRecord.objects.filter(dbid=a.dbid).update(
        received_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    )
    b = HistoryEntryFactory.create(external_id="00QB", action_taken="created")
    ResolutionAuditEntry.objects.filter(dbid=b.dbid).update(
        created_at=datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    )
    c = RowFactory.create(external_id="00QC")
    IncomingPatientRecord.objects.filter(dbid=c.dbid).update(
        received_at=datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    )
    d = HistoryEntryFactory.create(external_id="00QD", action_taken="modify_applied")
    ResolutionAuditEntry.objects.filter(dbid=d.dbid).update(
        created_at=datetime(2026, 1, 1, 4, 0, tzinfo=UTC)
    )

    first = _drive_activity(_make_api())
    assert [(e["kind"], e["external_id"]) for e in first["entries"]] == [
        ("decision", "00QD"),
        ("received", "00QC"),
    ]
    assert first["has_more"] is True

    cursor = first["next_cursor"]
    second = _drive_activity(
        _make_api(
            {
                "before": cursor["ts"],
                "before_kind": cursor["kind"],
                "before_id": str(cursor["id"]),
            }
        )
    )
    assert [(e["kind"], e["external_id"]) for e in second["entries"]] == [
        ("decision", "00QB"),
        ("received", "00QA"),
    ]
    assert second["has_more"] is False
    assert second["next_cursor"] is None


# ---------------------------------------------------------------------------
# record trail endpoint
# ---------------------------------------------------------------------------


def _drive_trail(api: SalesforceStatusAPI, external_id: str) -> dict[str, Any]:
    api.request = MagicMock()
    api.request.path_params = {"external_id": external_id}
    return _json_body(api.record_trail()[0])


def test_record_trail_merges_events_and_decisions_newest_first() -> None:
    """The trail merges the event log and the decision log, newest first."""
    from datetime import UTC, datetime

    event = RowFactory.create(
        external_id="00QTRAIL", action="modify", status="accepted"
    )
    IncomingPatientRecord.objects.filter(dbid=event.dbid).update(
        received_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    )
    decision = HistoryEntryFactory.create(
        external_id="00QTRAIL",
        event_id=event.pk,
        action="modify",
        action_taken="modify_applied",
    )
    ResolutionAuditEntry.objects.filter(dbid=decision.dbid).update(
        created_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    )

    body = _drive_trail(_make_api(), "00QTRAIL")

    assert body["external_id"] == "00QTRAIL"
    kinds = [item["kind"] for item in body["trail"]]
    assert kinds == ["decision", "received"]


def test_record_trail_empty_for_unknown_record() -> None:
    """An external id with no events or decisions yields an empty trail."""
    body = _drive_trail(_make_api(), "00QNONE")

    assert body["external_id"] == "00QNONE"
    assert body["trail"] == []


def test_record_trail_received_items_carry_event_id_and_payload() -> None:
    """A received trail item carries its event id and raw payload.

    The Activity Details modal shows the clicked event's payload, matched on the
    event id, so the trail received items must carry both. See journal
    cnv-928/030.
    """
    event = RowFactory.create(
        external_id="00QPAY",
        action="create",
        raw_payload={"Id": "00QPAY", "FirstName": "Ada"},
    )

    body = _drive_trail(_make_api(), "00QPAY")

    received = [item for item in body["trail"] if item["kind"] == "received"]
    assert len(received) == 1
    assert received[0]["event_id"] == event.pk
    assert received[0]["raw_payload"] == {"Id": "00QPAY", "FirstName": "Ada"}


# ---------------------------------------------------------------------------
# activity row links, Salesforce and patient chart
# ---------------------------------------------------------------------------
# _link_patient lives further down beside the trail snapshot test, reused here.


def test_activity_attaches_patient_id_only_for_linked_contacts() -> None:
    """A feed item carries the linked Canvas patient id, or empty when unlinked.

    The patient chart link shows only when a Canvas patient exists for the
    contact, resolved through the same salesforce identifier the Synced registry
    reads. See journal cnv-928/030.
    """
    linked = _link_patient("00QLINKED")
    RowFactory.create(external_id="00QLINKED", first_name="Ada", last_name="Lovelace")
    RowFactory.create(external_id="00QLOOSE", first_name="Mae", last_name="Jemison")

    body = _drive_activity(_make_api())

    by_external = {e["external_id"]: e for e in body["entries"]}
    assert by_external["00QLINKED"]["patient_id"] == str(linked.id)
    assert by_external["00QLOOSE"]["patient_id"] == ""


def test_activity_feed_item_carries_salesforce_url_with_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A feed item carries the Salesforce record link when a token is present.

    The link is built from the live instance url the token carries and the event
    source object, the same derivation the Synced row uses. See journal
    cnv-928/030.
    """

    class _StubToken:
        instance_url = "https://org.lightning.force.com"

    class _StubTokenStore:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def load(self) -> "_StubToken":
            return _StubToken()

    monkeypatch.setattr(status_api, "TokenStore", _StubTokenStore)

    RowFactory.create(
        external_id="00QSF", source_object="Contact", first_name="Ada"
    )

    body = _drive_activity(_make_api())

    arrival = next(e for e in body["entries"] if e["external_id"] == "00QSF")
    assert (
        arrival["salesforce_url"]
        == "https://org.lightning.force.com/lightning/r/Contact/00QSF/view"
    )


def test_activity_feed_item_has_empty_salesforce_url_without_a_token() -> None:
    """With no token the Salesforce link is empty so the row renders a dash."""
    RowFactory.create(external_id="00QNOSF", source_object="Contact")

    body = _drive_activity(_make_api())

    arrival = next(e for e in body["entries"] if e["external_id"] == "00QNOSF")
    assert arrival["salesforce_url"] == ""


def _link_patient(external_id: str, **kwargs: Any) -> Any:
    from datetime import date, timedelta

    from canvas_sdk.test_utils.factories import PatientFactory
    from canvas_sdk.v1.data.patient import PatientExternalIdentifier

    patient = PatientFactory.create(**kwargs)
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system="salesforce",
        value=external_id,
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )
    return patient


def test_record_trail_carries_canvas_and_salesforce_snapshots() -> None:
    """The trail response carries the Canvas patient and the latest Salesforce data.

    The Canvas snapshot feeds the Synced Details identity card, the source of truth
    for who the linked person is. The Salesforce snapshot is still served for any
    caller that wants the freshest payload, though the Synced comparison that once
    paired them is dropped. See journal cnv-928/026 and 037.
    """
    patient = _link_patient("00QCMP", first_name="Carla", last_name="Chart")
    RowFactory.create(
        external_id="00QCMP",
        action="create",
        raw_payload={"Id": "00QCMP", "FirstName": "Sally", "LastName": "Source"},
    )

    body = _drive_trail(_make_api(), "00QCMP")

    assert body["canvas"]["first_name"] == patient.first_name
    assert body["canvas"]["last_name"] == patient.last_name
    assert body["salesforce"]["first_name"] == "Sally"
    assert body["salesforce"]["last_name"] == "Source"


def test_record_trail_snapshots_empty_without_link_or_event() -> None:
    """The snapshots degrade to empty for an unlinked record with no events."""
    body = _drive_trail(_make_api(), "00QNONE2")

    assert body["canvas"] == {}
    assert body["salesforce"] == {}
