"""Behavioral tests for the four CronTask handlers (thin wrappers over the sync logic).

Each handler is instantiated bare (``__new__`` + set ``secrets``) since ``execute()`` only reads
``self.secrets``; the underlying module functions are mocked so we assert delegation/return wiring
without DB or network.
"""

from types import SimpleNamespace

from gcal_sync.channels import ChannelConfigError
from gcal_sync.google.client import GoogleApiError
from gcal_sync.handlers.block_sweep import BlockSweepCron
from gcal_sync.handlers.channel_renewal import ChannelRenewalCron
from gcal_sync.handlers.reconciliation import ReconciliationCron


def _cron(cls, secrets=None):
    handler = cls.__new__(cls)
    handler.secrets = secrets or {}
    return handler


# --- BlockSweepCron -----------------------------------------------------------------------------

def test_block_sweep_noop_without_mappings(mocker):
    mocker.patch(
        "gcal_sync.handlers.block_sweep.StaffCalendarMapping"
    ).objects.filter.return_value = []
    swept = mocker.patch("gcal_sync.handlers.block_sweep.sync_all_blocks")
    assert _cron(BlockSweepCron).execute() == []
    swept.assert_not_called()


def test_block_sweep_delegates_when_mappings_exist(mocker):
    mocker.patch(
        "gcal_sync.handlers.block_sweep.StaffCalendarMapping"
    ).objects.filter.return_value = [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c")]
    swept = mocker.patch(
        "gcal_sync.handlers.block_sweep.sync_all_blocks", return_value={"pushed": 2, "deleted": 1}
    )
    assert _cron(BlockSweepCron, {"k": "v"}).execute() == []
    swept.assert_called_once()


# --- ReconciliationCron -------------------------------------------------------------------------

def test_reconciliation_returns_inbound_effects(mocker):
    mocker.patch(
        "gcal_sync.handlers.reconciliation.reconcile_all",
        return_value=({"mappings": 1, "pushed": 3}, ["HOLD_EFFECT"]),
    )
    assert _cron(ReconciliationCron).execute() == ["HOLD_EFFECT"]


# --- ChannelRenewalCron -------------------------------------------------------------------------

def test_channel_renewal_noop_without_config(mocker):
    mocker.patch(
        "gcal_sync.handlers.channel_renewal.ChannelManager",
        side_effect=ChannelConfigError("no webhook config"),
    )
    assert _cron(ChannelRenewalCron).execute() == []


def test_channel_renewal_renews_each_active_calendar(mocker):
    manager = mocker.patch("gcal_sync.handlers.channel_renewal.ChannelManager").return_value
    manager.renew_if_needed.return_value = True
    mocker.patch(
        "gcal_sync.handlers.channel_renewal._active_calendar_ids", return_value=["c1", "c2"]
    )
    assert _cron(ChannelRenewalCron).execute() == []
    assert manager.renew_if_needed.call_count == 2


def test_channel_renewal_swallows_per_calendar_errors(mocker):
    manager = mocker.patch("gcal_sync.handlers.channel_renewal.ChannelManager").return_value
    manager.renew_if_needed.side_effect = GoogleApiError(500, "boom")
    mocker.patch("gcal_sync.handlers.channel_renewal._active_calendar_ids", return_value=["c1"])
    # One calendar failing must not raise — it's logged and the run completes.
    assert _cron(ChannelRenewalCron).execute() == []
