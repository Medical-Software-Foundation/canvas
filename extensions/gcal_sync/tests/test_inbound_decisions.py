"""Tests for InboundSync routing: echo-drop, appointment-revert, and admin-hold create/update/delete.

Models and effect-builders are mocked so no DB or network is needed. We assert which branch runs and
what effects come back.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from gcal_sync.google.event_builder import CANVAS_APPT_ID_KEY, build_event_body, content_hash
from gcal_sync.inbound import InboundSync

SECRETS = {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'}


def _inbound(mocker):
    inbound = InboundSync(SECRETS, client_factory=lambda cal: object())
    mocker.patch.object(inbound._sync, "push")
    mocker.patch.object(inbound._sync, "remove")
    return inbound


def _stats():
    return {
        "processed": 0,
        "echoes": 0,
        "reverted": 0,
        "holds_created": 0,
        "holds_updated": 0,
        "holds_removed": 0,
        "ignored": 0,
        "full_resync": False,
    }


def _pushed_event(appt_id="appt-1"):
    body = build_event_body(
        {
            "appointment_id": appt_id,
            "visit_type": "Visit",
            "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
            "duration_minutes": 30,
            "location": "Clinic",
            "meeting_link": None,
            "status": "confirmed",
        }
    )
    event = dict(body)
    event["id"] = "g-1"
    return event, content_hash(body)


# --- marked events (our own canvasApptId stamp) -------------------------------------------------

def test_marked_echo_is_dropped(mocker):
    event, pushed_hash = _pushed_event()
    mocker.patch(
        "gcal_sync.inbound.AppointmentEventMapping"
    ).objects.filter.return_value.first.return_value = SimpleNamespace(last_pushed_hash=pushed_hash)
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["echoes"] == 1
    inbound._sync.push.assert_not_called()


def test_marked_provider_edit_reverts_to_canvas(mocker):
    event, pushed_hash = _pushed_event()
    event["summary"] = "Provider changed this"
    mocker.patch(
        "gcal_sync.inbound.AppointmentEventMapping"
    ).objects.filter.return_value.first.return_value = SimpleNamespace(last_pushed_hash=pushed_hash)
    mocker.patch(
        "gcal_sync.inbound.build_snapshot", return_value=({"appointment_id": "appt-1"}, "s1", False)
    )
    inbound = _inbound(mocker)
    stats = _stats()
    inbound._apply("cal", event, stats)
    assert stats["reverted"] == 1
    inbound._sync.push.assert_called_once()


# --- unmarked events (provider-created in Google) -> admin holds --------------------------------

def test_unmarked_new_event_creates_hold(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    # Import context (note-type + provider/location) is resolved once per calendar; mock the resolvers.
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-new", "status": "confirmed", "summary": "Hold"}, stats)
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1
    iem.objects.update_or_create.assert_called_once()


def test_unmarked_unresolvable_hold_is_ignored(mocker):
    mocker.patch("gcal_sync.inbound.InboundEventMapping").objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    # build_hold_effect returns None (e.g. event time unparseable) -> skip, no create.
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value=None)
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-new", "status": "confirmed"}, stats)
    assert effects == []
    assert stats["ignored"] == 1


def test_unmarked_known_event_updates_hold(mocker):
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = SimpleNamespace(google_event_id="g-1")
    inbound = _inbound(mocker)
    # A live Canvas hold exists for this mapping -> take the update path.
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-99")
    mocker.patch.object(inbound, "_hold_update_effect", return_value="UPDATE_EFFECT")
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-1", "status": "confirmed", "summary": "Edited"}, stats)
    assert effects == ["UPDATE_EFFECT"]
    assert stats["holds_updated"] == 1


def test_unmarked_orphaned_mapping_recreates_hold(mocker):
    # Mapping row exists but no live Canvas hold AND it predates the pending-create grace window (a
    # prior run was interrupted/capped before the create applied). RE-CREATE it, don't skip (#4).
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = SimpleNamespace(
        google_event_id="g-1", created_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)  # orphaned
    update_spy = mocker.patch.object(inbound, "_hold_update_effect")
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-1", "status": "confirmed", "summary": "Hold"}, stats)
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1
    update_spy.assert_not_called()
    iem.objects.update_or_create.assert_called_once()


def test_unmarked_pending_create_is_not_duplicated(mocker):
    # Mapping was written moments ago but the async create hasn't applied yet (no live hold). A
    # re-delivered webhook must NOT re-issue the create — re-creating in-flight holds is what
    # produced the duplicate-hold storm under load.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = SimpleNamespace(
        google_event_id="g-1", created_at=datetime.now(timezone.utc)
    )
    build = mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)  # not applied yet
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-1", "status": "confirmed", "summary": "Hold"}, stats)
    assert effects == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1
    build.assert_not_called()
    iem.objects.update_or_create.assert_not_called()


def test_unmarked_cancelled_known_event_removes_hold(mocker):
    existing = SimpleNamespace(google_event_id="g-1", delete=mocker.Mock())
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = existing
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_hold_delete_effect", return_value="DELETE_EFFECT")
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-1", "status": "cancelled"}, stats)
    assert effects == ["DELETE_EFFECT"]
    assert stats["holds_removed"] == 1
    existing.delete.assert_called_once()


def test_unmarked_event_without_id_is_ignored(mocker):
    inbound = _inbound(mocker)
    stats = _stats()
    assert inbound._apply("cal", {"status": "confirmed"}, stats) == []
    assert stats["ignored"] == 1


def test_update_masks_private_event_title(mocker):
    # Editing a private Google event must NOT leak its real title into Canvas — it stays "Busy".
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    mocker.patch(
        "gcal_sync.inbound.parse_event_window",
        return_value=(datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc), 30),
    )
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent").return_value
    inbound._hold_update_effect(
        "g-1", {"id": "g-1", "visibility": "private", "summary": "Dad - Dr. Appt"}
    )
    assert se.description == "Busy"


def test_update_keeps_public_event_title(mocker):
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    mocker.patch(
        "gcal_sync.inbound.parse_event_window",
        return_value=(datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc), 30),
    )
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent").return_value
    inbound._hold_update_effect("g-1", {"id": "g-1", "summary": "Standup"})
    assert se.description == "Standup"
