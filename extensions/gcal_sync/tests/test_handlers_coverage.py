"""Tests for the two new CronTask handlers: OutboundBackfillDrainCron and ReimportDrainCron."""

from gcal_sync.handlers.outbound_backfill import OutboundBackfillDrainCron
from gcal_sync.handlers.reimport_drain import ReimportDrainCron


def _cron(cls, secrets=None):
    handler = cls.__new__(cls)
    handler.secrets = secrets or {}
    return handler


# --- OutboundBackfillDrainCron --------------------------------------------------------------------


def test_outbound_backfill_cron_delegates_to_drain(mocker):
    drain = mocker.patch(
        "gcal_sync.handlers.outbound_backfill.drain_outbound_backfill",
        return_value={"providers": 1, "pushed": 10, "skipped": 0},
    )
    result = _cron(OutboundBackfillDrainCron, {"KEY": "val"}).execute()
    assert result == []
    drain.assert_called_once_with({"KEY": "val"})


def test_outbound_backfill_cron_schedule():
    assert OutboundBackfillDrainCron.SCHEDULE == "*/2 * * * *"


# --- ReimportDrainCron ---------------------------------------------------------------------------


def test_reimport_drain_cron_returns_effects(mocker):
    mocker.patch(
        "gcal_sync.handlers.reimport_drain.drain_reimport_queue",
        return_value=({"processed": 1}, ["EFFECT_1", "EFFECT_2"]),
    )
    result = _cron(ReimportDrainCron, {"KEY": "val"}).execute()
    assert result == ["EFFECT_1", "EFFECT_2"]


def test_reimport_drain_cron_returns_empty_when_queue_empty(mocker):
    mocker.patch(
        "gcal_sync.handlers.reimport_drain.drain_reimport_queue",
        return_value=({"processed": 0}, []),
    )
    result = _cron(ReimportDrainCron).execute()
    assert result == []


def test_reimport_drain_cron_schedule():
    assert ReimportDrainCron.SCHEDULE == "*/2 * * * *"
