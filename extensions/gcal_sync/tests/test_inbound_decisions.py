"""Tests for InboundSync routing: echo-drop, appointment-revert, and admin-hold create/update/delete.

Models and effect-builders are mocked so no DB or network is needed. We assert which branch runs and
what effects come back.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


from gcal_sync.google.event_builder import (
    build_event_body,
    content_hash,
    google_event_content_hash,
)
from gcal_sync.inbound import InboundSync

SECRETS = {
    "GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'
}


def _inbound(mocker):
    inbound = InboundSync(SECRETS, client_factory=lambda cal: object())
    mocker.patch.object(inbound._sync, "push")
    mocker.patch.object(inbound._sync, "remove")
    # Resolved once per calendar at the top of _handle_unmarked_event; default it so routing tests
    # don't hit the DB. provider_id="prov-1" is what the per-provider hold lookups are scoped to.
    mocker.patch.object(
        inbound, "_import_context", return_value=("nt-1", "prov-1", "loc-1")
    )
    # Per-(calendar, event) pending-create marker: default to "no marker" so create-path routing
    # tests fall through to create. Tests that exercise the pending/orphan guard override this.
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = None
    return inbound


def _stats():
    return {
        "processed": 0,
        "echoes": 0,
        "reverted": 0,
        "holds_created": 0,
        "holds_updated": 0,
        "holds_unchanged": 0,
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
    ).objects.filter.return_value.first.return_value = SimpleNamespace(
        last_pushed_hash=pushed_hash
    )
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
    ).objects.filter.return_value.first.return_value = SimpleNamespace(
        last_pushed_hash=pushed_hash
    )
    mocker.patch(
        "gcal_sync.inbound.build_snapshot",
        return_value=({"appointment_id": "appt-1"}, "s1", False),
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
    mocker.patch(
        "gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1")
    )
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    effects = inbound._apply(
        "cal", {"id": "g-new", "status": "confirmed", "summary": "Hold"}, stats
    )
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1
    iem.objects.update_or_create.assert_called_once()


def test_unmarked_unresolvable_hold_is_ignored(mocker):
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch(
        "gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1")
    )
    # build_hold_effect returns None (e.g. event time unparseable) -> skip, no create.
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value=None)
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-new", "status": "confirmed"}, stats)
    assert effects == []
    assert stats["ignored"] == 1


def test_unmarked_known_event_updates_hold(mocker):
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = SimpleNamespace(
        google_event_id="g-1", last_applied_hash=""
    )
    inbound = _inbound(mocker)
    # A live Canvas hold exists and the event content differs from what we last applied -> update.
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-99")
    mocker.patch.object(inbound, "_hold_update_effect", return_value="UPDATE_EFFECT")
    stats = _stats()
    effects = inbound._apply(
        "cal", {"id": "g-1", "status": "confirmed", "summary": "Edited"}, stats
    )
    assert effects == ["UPDATE_EFFECT"]
    assert stats["holds_updated"] == 1


def test_unmarked_unchanged_event_skips_update(mocker):
    # A delta re-delivering an UNCHANGED event must NOT re-issue an UPDATE — the redundant hold
    # re-save that drove the api_appointment write load. Guard on the content hash we last applied.
    # Start is a few days out so it sits inside the import window (else the window gate ignores it
    # before the no-op guard runs); relative to now so the test can't rot out of the window.
    start = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0)
    event = {
        "id": "g-1",
        "status": "confirmed",
        "summary": "Standup",
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "end": {
            "dateTime": (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        },
    }
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = SimpleNamespace(
        google_event_id="g-1", last_applied_hash=google_event_content_hash(event)
    )
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-99")
    update_spy = mocker.patch.object(inbound, "_hold_update_effect")
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["holds_unchanged"] == 1
    assert stats["holds_updated"] == 0
    update_spy.assert_not_called()


def test_unmarked_orphaned_mapping_recreates_hold(mocker):
    # A pending marker exists but no live Canvas hold AND it predates the grace window (a prior run
    # was interrupted/capped before the create applied). RE-CREATE it, don't skip (#4).
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch(
        "gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1")
    )
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    # Stale pending marker (past grace) -> genuine orphan, re-create.
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = SimpleNamespace(
        created_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    mocker.patch.object(
        inbound, "_canvas_id_for_google_event", return_value=None
    )  # orphaned
    # Genuine orphan: the create never applied, so no external id exists for this event.
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    update_spy = mocker.patch.object(inbound, "_hold_update_effect")
    stats = _stats()
    effects = inbound._apply(
        "cal", {"id": "g-1", "status": "confirmed", "summary": "Hold"}, stats
    )
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1
    update_spy.assert_not_called()
    pending.objects.update_or_create.assert_called_once()  # marker refreshed for the new attempt


def test_unmarked_pending_create_is_not_duplicated(mocker):
    # A pending marker for THIS calendar was written moments ago but the async create hasn't applied
    # yet (no live hold). A re-delivered webhook must NOT re-issue the create — re-creating in-flight
    # holds is what produced the duplicate-hold storm under load.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    build = mocker.patch(
        "gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT"
    )
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = SimpleNamespace(
        created_at=datetime.now(timezone.utc)  # within grace -> still in flight
    )
    mocker.patch.object(
        inbound, "_canvas_id_for_google_event", return_value=None
    )  # not applied yet
    mocker.patch.object(
        inbound, "_external_hold_exists", return_value=False
    )  # no external id yet
    stats = _stats()
    effects = inbound._apply(
        "cal", {"id": "g-1", "status": "confirmed", "summary": "Hold"}, stats
    )
    assert effects == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1
    build.assert_not_called()
    pending.objects.update_or_create.assert_not_called()


def test_unmarked_far_future_event_is_skipped(mocker):
    # Fix 1: a token-based delta pull sends no timeMax, so Google expands a recurring series to its
    # instances out to year 2099. An event starting beyond the 6-month import window must never be
    # materialized as a hold — this per-event guard is the real bound on recurring expansion.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    build = mocker.patch(
        "gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT"
    )
    inbound = _inbound(mocker)
    stats = _stats()
    event = {
        "id": "g-future",
        "status": "confirmed",
        "summary": "Weekly standup",
        "start": {"dateTime": "2028-06-10T15:00:00Z"},
        "end": {"dateTime": "2028-06-10T15:30:00Z"},
    }
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1
    build.assert_not_called()
    iem.objects.update_or_create.assert_not_called()


def test_unmarked_cancelled_hold_is_not_recreated(mocker):
    # Fix 2 (convergence): a hold was created for this event and later cancelled (Google deletion we
    # processed, or drained by the purge). ScheduleEvent has no revive, so re-creating it is the
    # create -> cancel -> re-create loop that minted 260k cancelled duplicate holds. Leave it cancelled.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    build = mocker.patch(
        "gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT"
    )
    inbound = _inbound(mocker)
    mocker.patch.object(
        inbound, "_canvas_id_for_google_event", return_value=None
    )  # no LIVE hold
    mocker.patch.object(
        inbound, "_external_hold_exists", return_value=True
    )  # but a cancelled one exists
    stats = _stats()
    effects = inbound._apply(
        "cal", {"id": "g-1", "status": "confirmed", "summary": "Hold"}, stats
    )
    assert effects == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1
    build.assert_not_called()
    iem.objects.update_or_create.assert_not_called()


def test_force_rebuild_recreates_cancelled_hold(mocker):
    # The deliberate admin "Re-import" path bypasses the convergence guard: an event whose only hold
    # is cancelled IS recreated. This is what lets a drained provider's holds be rebuilt (the holds
    # are the feature — Google must reflect real availability), without the routine webhook/reconcile
    # paths ever re-inflating a purge.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch(
        "gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1")
    )
    build = mocker.patch(
        "gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT"
    )
    inbound = _inbound(mocker)
    mocker.patch.object(
        inbound, "_canvas_id_for_google_event", return_value=None
    )  # no live hold
    mocker.patch.object(
        inbound, "_external_hold_exists", return_value=True
    )  # only a cancelled one
    stats = _stats()
    effects = inbound._apply(
        "cal",
        {"id": "g-1", "status": "confirmed", "summary": "Hold"},
        stats,
        force_rebuild=True,
    )
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1
    build.assert_called_once()
    iem.objects.update_or_create.assert_called_once()


def test_unmarked_live_hold_updates_even_without_mapping(mocker):
    # Fix 2 robustness: a live hold exists but its InboundEventMapping row was lost. Update in place
    # rather than falling through to create (which duplicated the hold when the mapping went missing).
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = None
    inbound = _inbound(mocker)
    mocker.patch.object(
        inbound, "_canvas_id_for_google_event", return_value="appt-live"
    )
    mocker.patch.object(inbound, "_hold_update_effect", return_value="UPDATE_EFFECT")
    stats = _stats()
    effects = inbound._apply(
        "cal", {"id": "g-1", "status": "confirmed", "summary": "Edited"}, stats
    )
    assert effects == ["UPDATE_EFFECT"]
    assert stats["holds_updated"] == 1


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
        "g-1",
        {"id": "g-1", "visibility": "private", "summary": "Dad - Dr. Appt"},
        "prov-1",
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
    inbound._hold_update_effect("g-1", {"id": "g-1", "summary": "Standup"}, "prov-1")
    assert se.description == "Standup"


# --- per-provider hold scoping (shared multi-attendee events) -----------------------------------
# A shared Google event carries the SAME id on every attendee's calendar. Every hold lookup is
# scoped to the calendar's provider so each attendee gets their own Canvas hold instead of all but
# the first being skipped (the bug where a provider's shared meetings never imported).


def test_canvas_id_lookup_is_scoped_to_provider(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value.first.return_value = 42
    inbound = _inbound(mocker)
    assert inbound._canvas_id_for_google_event("g-1", "prov-7") == "42"
    _, kwargs = aei.objects.filter.call_args
    assert kwargs["value"] == "g-1"
    assert kwargs["appointment__provider__id"] == "prov-7"


def test_external_hold_exists_is_scoped_to_provider(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exists.return_value = True
    inbound = _inbound(mocker)
    assert inbound._external_hold_exists("g-1", "prov-7") is True
    _, kwargs = aei.objects.filter.call_args
    assert kwargs["value"] == "g-1"
    assert kwargs["appointment__provider__id"] == "prov-7"


def _provider_scoped_aei(mocker, provider_with_hold):
    """Patch AppointmentExternalIdentifier so a live hold exists ONLY for ``provider_with_hold``.

    Mirrors the DB behavior the scoping relies on: filtering the same shared event id by a different
    provider returns no hold. Returns the patched mock so callers can inspect ``.filter`` calls.
    """
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")

    def filter_side_effect(**kwargs):
        qs = mocker.MagicMock()
        has_hold = kwargs.get("appointment__provider__id") == provider_with_hold
        qs.exclude.return_value.values_list.return_value.first.return_value = (
            500 if has_hold else None
        )
        qs.exists.return_value = has_hold
        return qs

    aei.objects.filter.side_effect = filter_side_effect
    return aei


def test_shared_event_on_other_provider_does_not_block_this_provider(mocker):
    # Provider A already has a live hold for a shared event; syncing provider B's calendar (prov-1,
    # per _inbound's _import_context) must still CREATE B's own hold, not be routed into A's update.
    _provider_scoped_aei(mocker, provider_with_hold="prov-A")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)  # _import_context -> provider prov-1 (B)
    stats = _stats()
    effects = inbound._apply(
        "calB", {"id": "shared-1", "status": "confirmed", "summary": "Team sync"}, stats
    )
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1


def test_shared_event_on_owning_provider_updates_in_place(mocker):
    # The other side of the same shared event: syncing provider A's calendar finds A's own live hold
    # under scope and UPDATES it rather than minting a second one.
    _provider_scoped_aei(mocker, provider_with_hold="prov-A")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.ScheduleEvent")
    inbound = _inbound(mocker)
    mocker.patch.object(
        inbound, "_import_context", return_value=("nt-1", "prov-A", "loc-1")
    )
    start = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0)
    event = {
        "id": "shared-1",
        "status": "confirmed",
        "summary": "Team sync",
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "end": {
            "dateTime": (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        },
    }
    stats = _stats()
    inbound._apply("calA", event, stats)
    assert stats["holds_updated"] == 1
    assert stats["holds_created"] == 0


def test_cancelled_event_delete_is_scoped_to_provider(mocker):
    # Cancelling a shared event removes only THIS provider's hold: the delete targets the id resolved
    # under this provider's scope, another attendee's hold for the same event id is untouched.
    aei = _provider_scoped_aei(mocker, provider_with_hold="prov-1")
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    existing = SimpleNamespace(delete=mocker.Mock())
    iem.objects.filter.return_value.first.return_value = existing
    inbound = _inbound(mocker)  # prov-1
    stats = _stats()
    effects = inbound._apply("calB", {"id": "shared-1", "status": "cancelled"}, stats)
    assert stats["holds_removed"] == 1
    assert effects == [se.return_value.delete.return_value]
    se.assert_called_once_with(instance_id="500")
    existing.delete.assert_called_once()
    delete_call = [c for c in aei.objects.filter.call_args_list][-1]
    assert delete_call.kwargs["appointment__provider__id"] == "prov-1"


def test_existing_mapping_lookup_is_scoped_by_calendar(mocker):
    # The advisory InboundEventMapping row is looked up scoped to this calendar so a shared event's
    # single row (unique per event id, owned by whichever attendee synced last) can't suppress this
    # provider's import.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    inbound._apply(
        "calB", {"id": "shared-1", "status": "confirmed", "summary": "x"}, stats
    )
    _, kwargs = iem.objects.filter.call_args
    assert kwargs["google_event_id"] == "shared-1"
    assert kwargs["google_calendar_id"] == "calB"


def test_apply_passes_resolved_provider_into_hold_lookups(mocker):
    # The provider resolved once at the top of _handle_unmarked_event flows into every hold lookup.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)  # _import_context -> prov-1
    canvas_id_spy = mocker.patch.object(
        inbound, "_canvas_id_for_google_event", return_value=None
    )
    ext_spy = mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    inbound._apply(
        "calB", {"id": "shared-1", "status": "confirmed", "summary": "x"}, stats
    )
    canvas_id_spy.assert_called_with("shared-1", "prov-1")
    ext_spy.assert_called_with("shared-1", "prov-1")


# --- dupe-safety: fan-out to every attendee, re-import idempotency, steady-state convergence -----
# The per-provider scoping must (a) give EACH attendee of a shared event their own hold, and
# (b) never mint a SECOND live hold for a provider that already has one — on webhook, reconcile, or
# a force-rebuild re-import.


def _multi_provider_aei(mocker, providers_with_hold):
    """Patch AppointmentExternalIdentifier so a live hold exists only for providers in the set."""
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")

    def filter_side_effect(**kwargs):
        qs = mocker.MagicMock()
        has = kwargs.get("appointment__provider__id") in providers_with_hold
        qs.exclude.return_value.values_list.return_value.first.return_value = (
            900 if has else None
        )
        qs.exists.return_value = has
        return qs

    aei.objects.filter.side_effect = filter_side_effect
    return aei


def test_shared_event_fans_out_to_every_attendee(mocker):
    # A 3-attendee event: providers A and B already hold it; syncing the third (prov-1, per _inbound)
    # must CREATE its own hold rather than being suppressed by the other two.
    _multi_provider_aei(mocker, providers_with_hold={"prov-A", "prov-B"})
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)  # third attendee = prov-1
    stats = _stats()
    effects = inbound._apply(
        "calC", {"id": "shared-1", "status": "confirmed", "summary": "Team sync"}, stats
    )
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1


def test_reimport_updates_existing_live_hold_never_duplicates(mocker):
    # Re-import (force_rebuild) of a provider who ALREADY has a live hold must UPDATE in place, not
    # create a second one — the live-hold guard runs before the force-rebuild convergence bypass.
    _multi_provider_aei(
        mocker, providers_with_hold={"prov-1"}
    )  # prov-1 has a live hold
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    build = mocker.patch(
        "gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT"
    )
    mocker.patch("gcal_sync.inbound.ScheduleEvent")
    inbound = _inbound(mocker)
    start = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0)
    event = {
        "id": "shared-1",
        "status": "confirmed",
        "summary": "Edited",
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "end": {
            "dateTime": (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        },
    }
    stats = _stats()
    inbound._apply("calB", event, stats, force_rebuild=True)
    assert stats["holds_updated"] == 1
    assert stats["holds_created"] == 0
    build.assert_not_called()  # never built a create effect


def test_steady_state_never_recreates_this_providers_cancelled_hold(mocker):
    # Routine sync (NOT force_rebuild): this provider's only hold for the event is cancelled. The
    # per-provider convergence guard must still refuse to re-create it, even though another attendee
    # holds a live copy of the same shared event.
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")

    def filter_side_effect(**kwargs):
        qs = mocker.MagicMock()
        pid = kwargs.get("appointment__provider__id")
        # prov-1 (this provider): a cancelled hold exists -> no LIVE id, but external hold exists.
        # prov-OTHER: a live hold exists.
        qs.exclude.return_value.values_list.return_value.first.return_value = (
            700 if pid == "prov-OTHER" else None
        )
        qs.exists.return_value = pid in ("prov-1", "prov-OTHER")
        return qs

    aei.objects.filter.side_effect = filter_side_effect
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    build = mocker.patch(
        "gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT"
    )
    inbound = _inbound(mocker)  # prov-1
    stats = _stats()
    effects = inbound._apply(
        "calB", {"id": "shared-1", "status": "confirmed", "summary": "x"}, stats
    )
    assert effects == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1
    build.assert_not_called()


# --- dry_run: identical decisions, ZERO side effects (the pre-deploy preview) -------------------


def test_dry_run_create_counts_but_writes_nothing(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = None
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    effects = inbound._apply(
        "cal",
        {"id": "g-new", "status": "confirmed", "summary": "Hold"},
        stats,
        dry_run=True,
    )
    assert effects == ["HOLD_EFFECT"]  # the would-be effect is still surfaced
    assert stats["holds_created"] == 1  # ...and counted
    iem.objects.update_or_create.assert_not_called()  # but NOTHING is written
    pending.objects.update_or_create.assert_not_called()  # ...including the pending marker


def test_create_writes_pending_marker_scoped_to_calendar(mocker):
    # On a real create the per-(calendar, event) marker is written so a same-calendar replay is
    # deduped; and the pending lookup is scoped by calendar so a co-attendee's marker never blocks us.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = (
        None  # no marker on THIS calendar
    )
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    effects = inbound._apply(
        "calB", {"id": "shared-1", "status": "confirmed", "summary": "Team sync"}, stats
    )
    assert effects == ["HOLD_EFFECT"]
    assert stats["holds_created"] == 1
    # lookup scoped to this calendar (so a marker on another attendee's calendar can't suppress us)
    _, lookup_kwargs = pending.objects.filter.call_args
    assert lookup_kwargs == {
        "google_event_id": "shared-1",
        "google_calendar_id": "calB",
    }
    # marker written for exactly (this calendar, this event)
    write_kwargs = pending.objects.update_or_create.call_args.kwargs
    assert write_kwargs["google_event_id"] == "shared-1"
    assert write_kwargs["google_calendar_id"] == "calB"


def test_dry_run_update_writes_no_mapping(mocker):
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = None
    inbound = _inbound(mocker)
    mocker.patch.object(
        inbound, "_canvas_id_for_google_event", return_value="appt-live"
    )
    mocker.patch.object(inbound, "_hold_update_effect", return_value="UPDATE_EFFECT")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    stats = _stats()
    effects = inbound._apply(
        "cal",
        {"id": "g-1", "status": "confirmed", "summary": "Edited"},
        stats,
        dry_run=True,
    )
    assert effects == ["UPDATE_EFFECT"]
    assert stats["holds_updated"] == 1
    iem.objects.update_or_create.assert_not_called()


def test_dry_run_cancel_does_not_delete_mapping(mocker):
    existing = SimpleNamespace(google_event_id="g-1", delete=mocker.Mock())
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = existing
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_hold_delete_effect", return_value="DELETE_EFFECT")
    stats = _stats()
    effects = inbound._apply(
        "cal", {"id": "g-1", "status": "cancelled"}, stats, dry_run=True
    )
    assert effects == ["DELETE_EFFECT"]  # the would-be delete is surfaced
    assert stats["holds_removed"] == 1
    existing.delete.assert_not_called()  # but the mapping row is left intact


# --- dry-run trace: per-event preview lines returned to the admin UI ----------------------------


def _future_event(**extra):
    start = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0)
    event = {
        "id": "g-new",
        "status": "confirmed",
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "end": {
            "dateTime": (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        },
    }
    event.update(extra)
    return event


def test_dry_run_trace_records_per_event_outcome(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = None
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    stats["trace"] = []  # process_calendar seeds this only in dry-run
    inbound._apply("cal", _future_event(summary="Team Sync"), stats, dry_run=True)
    assert stats["holds_created"] == 1
    # a human-readable preview line naming the outcome and the event is collected
    assert any(
        "would import" in line and "Team Sync" in line for line in stats["trace"]
    )


def test_dry_run_trace_masks_private_event_title(mocker):
    # A private event still imports (masked) — its preview line must show "Busy", never the real
    # PHI-adjacent title, matching what the hold itself would display.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = None
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    stats["trace"] = []
    inbound._apply(
        "cal",
        _future_event(visibility="private", summary="Dad - Dr. Appt"),
        stats,
        dry_run=True,
    )
    line = " ".join(stats["trace"])
    assert "Busy" in line
    assert (
        "Dad - Dr. Appt" not in line
    )  # real title never surfaces, even in the preview


def test_no_trace_collected_outside_dry_run(mocker):
    # Steady-state (no dry-run) must not build a trace — stats has no 'trace' key and none appears.
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = None
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    inbound._apply("cal", _future_event(summary="Team Sync"), stats)
    assert "trace" not in stats


def _gcal_outcomes(log_spy):
    """The per-event outcome strings the code logged via the 'gcal inbound: %s ...' template."""
    return [
        c.args[1]
        for c in log_spy.info.call_args_list
        if c.args
        and isinstance(c.args[0], str)
        and c.args[0].startswith("gcal inbound: %s")
    ]


def test_verbose_emits_a_per_event_log_line(mocker):
    # Single-provider re-import (verbose) logs a line per event outcome.
    log_spy = mocker.patch("gcal_sync.inbound.log")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = None
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    inbound._apply("cal", _future_event(summary="X"), stats, verbose=True)
    assert "create hold" in _gcal_outcomes(log_spy)


def test_non_verbose_suppresses_per_event_logs(mocker):
    # Fleet / steady-state (verbose=False, the default) logs no per-event lines — summaries only.
    log_spy = mocker.patch("gcal_sync.inbound.log")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    pending = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    pending.objects.filter.return_value.first.return_value = None
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    inbound._apply("cal", _future_event(summary="X"), stats)  # verbose defaults False
    assert _gcal_outcomes(log_spy) == []
