"""Tests for InboundSync.process_calendar: full-pull token advance, 410 recovery, safety cap."""

from types import SimpleNamespace

from gcal_sync.google.client import GoogleApiError
from gcal_sync.inbound import InboundSync

SECRETS = {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'}


def _state(mocker, sync_token="", needs=True):
    state = SimpleNamespace(sync_token=sync_token, needs_full_resync=needs, save=mocker.Mock())
    css = mocker.patch("gcal_sync.inbound.CalendarSyncState")
    css.objects.get_or_create.return_value = (state, False)
    return state


def _inbound(client):
    return InboundSync(SECRETS, allowed_changes=set(), client_factory=lambda c: client)


def test_import_context_caches_per_calendar_and_reresolves_on_change(mocker):
    nt = mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    pl = mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = InboundSync(SECRETS, allowed_changes=set(), client_factory=lambda c: object())
    # Repeated calls for the SAME calendar resolve only once (the per-event N+1 we removed).
    assert inbound._import_context("calA") == ("nt-1", "14", "loc-1")
    assert inbound._import_context("calA") == ("nt-1", "14", "loc-1")
    assert nt.call_count == 1 and pl.call_count == 1
    # A DIFFERENT calendar (bulk reconcile) re-resolves — no cross-provider leakage.
    inbound._import_context("calB")
    assert nt.call_count == 2 and pl.call_count == 2


def test_full_pull_advances_sync_token(mocker):
    state = _state(mocker)
    client = SimpleNamespace(
        list_event_deltas=mocker.Mock(return_value=([{"id": "g1"}], "newtok"))
    )
    inbound = _inbound(client)
    mocker.patch.object(inbound, "_apply", return_value=[])
    inbound.process_calendar("c1")
    assert state.sync_token == "newtok"
    assert state.needs_full_resync is False
    state.save.assert_called()


def test_410_clears_token_and_schedules_resync(mocker):
    state = _state(mocker, sync_token="tok", needs=False)
    client = SimpleNamespace(
        list_event_deltas=mocker.Mock(side_effect=GoogleApiError(410, "gone"))
    )
    stats, _ = _inbound(client).process_calendar("c1")
    assert stats["full_resync"] is True
    assert state.sync_token == ""
    assert state.needs_full_resync is True


def test_non_410_error_propagates(mocker):
    _state(mocker)
    client = SimpleNamespace(
        list_event_deltas=mocker.Mock(side_effect=GoogleApiError(500, "boom"))
    )
    import pytest

    with pytest.raises(GoogleApiError):
        _inbound(client).process_calendar("c1")


def test_safety_cap_aborts_without_advancing_cursor(mocker):
    state = _state(mocker)  # sync_token starts ""
    client = SimpleNamespace(
        list_event_deltas=mocker.Mock(return_value=([{"id": "g1"}, {"id": "g2"}], "newtok"))
    )
    inbound = _inbound(client)

    def over_cap(_cal, _event, stats):
        stats["holds_created"] = inbound._MAX_HOLDS_PER_RUN
        return []

    mocker.patch.object(inbound, "_apply", side_effect=over_cap)
    stats, _ = inbound.process_calendar("c1")
    assert stats["capped"] is True
    assert state.sync_token == ""  # cursor NOT advanced on abort
