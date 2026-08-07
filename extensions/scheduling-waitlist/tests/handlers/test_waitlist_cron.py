"""The nightly housekeeping job."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.waitlist_cron import WaitlistMaintenanceCron

MODULE = "scheduling_waitlist.handlers.waitlist_cron"


def _cron(secrets=None):
    cron = WaitlistMaintenanceCron.__new__(WaitlistMaintenanceCron)
    cron.event = MagicMock()
    cron.secrets = {"WAITLIST_TTL_DAYS": "60"} if secrets is None else secrets
    return cron


class _Queryset:
    def __init__(self, items=None):
        self.items = items or []
        self.deleted = False

    def filter(self, **kwargs):
        self.filter_kwargs = kwargs
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self

    def only(self, *args):
        return self

    def delete(self):
        self.deleted = True

    def __getitem__(self, item):
        return self.items

    def __iter__(self):
        return iter(self.items)


def _entry(status="waiting", created_days_ago=10, expires_on=None):
    entry = MagicMock()
    entry.status = status
    entry.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    entry.expires_on = expires_on
    return entry


def _run(cron, *, missing=None, due=None, report=None):
    """Drive the job with a scripted set of query results."""
    missing_qs = _Queryset(missing or [])
    due_qs = _Queryset(due or [])
    report_qs = _Queryset(report or [])
    notification_qs = _Queryset()
    calls = {"n": 0}

    def entry_filter(**kwargs):
        calls["n"] += 1
        if kwargs.get("expires_on__isnull"):
            return missing_qs
        return due_qs

    with (
        patch(f"{MODULE}.WaitlistEntry") as entry_model,
        patch(f"{MODULE}.SlotNotification") as notification_model,
    ):
        entry_model.objects.filter.side_effect = entry_filter
        entry_model.objects.all.return_value = report_qs
        notification_model.objects.filter.return_value = notification_qs
        cron.execute()
        return entry_model, notification_qs


class TestSchedule:
    def test_runs_nightly(self):
        assert WaitlistMaintenanceCron.SCHEDULE == "0 3 * * *"


class TestShelfLifeConfiguration:
    def test_nothing_is_aged_out_without_a_configured_shelf_life(self):
        # Expiring entries is destructive; a mistyped setting must not be the
        # reason somebody drops off the list.
        entry_model, _ = _run(_cron(secrets={}), due=[_entry()])

        entry_model.objects.bulk_update.assert_not_called()

    def test_an_invalid_shelf_life_ages_nothing_out(self):
        entry_model, _ = _run(
            _cron(secrets={"WAITLIST_TTL_DAYS": "soon"}), due=[_entry()]
        )

        entry_model.objects.bulk_update.assert_not_called()

    def test_the_missing_configuration_is_logged_as_an_error(self):
        import sys

        _run(_cron(secrets={}))

        assert sys.modules["logger"].log.error.called


class TestAgeing:
    def test_entries_past_their_shelf_life_are_marked_expired(self):
        entry = _entry(expires_on=date(2026, 1, 1))

        entry_model, _ = _run(_cron(), due=[entry])

        assert entry.status == "expired"
        entry_model.objects.bulk_update.assert_called()

    def test_ageing_records_why(self):
        entry = _entry(expires_on=date(2026, 1, 1))

        _run(_cron(), due=[entry])

        assert "shelf life" in entry.status_reason

    def test_ageing_is_a_status_change_not_a_deletion(self):
        # The wait-time reporting depends on these rows, and reinstating an
        # entry should not mean re-keying it.
        entry = _entry(expires_on=date(2026, 1, 1))

        _run(_cron(), due=[entry])

        entry.delete.assert_not_called()

    def test_nothing_due_writes_nothing(self):
        entry_model, _ = _run(_cron(), due=[])

        entry_model.objects.bulk_update.assert_not_called()


class TestBackfill:
    def test_entries_without_an_expiry_date_are_given_one(self):
        # The schema pipeline emits no column defaults, so rows written before
        # this column existed would otherwise never lapse.
        entry = _entry(created_days_ago=10, expires_on=None)

        _run(_cron(), missing=[entry])

        assert entry.expires_on is not None

    def test_the_expiry_is_measured_from_when_the_entry_was_added(self):
        entry = _entry(created_days_ago=10, expires_on=None)

        _run(_cron(), missing=[entry])

        expected = (datetime.now(timezone.utc) - timedelta(days=10)).date() + timedelta(
            days=60
        )
        assert entry.expires_on == expected


class TestPruning:
    def test_old_slot_announcements_are_deleted(self):
        # Pure machine state with no value once the slot has passed.
        _, notification_qs = _run(_cron())

        assert notification_qs.deleted is True


class TestReporting:
    def test_the_summary_is_logged(self):
        import sys

        _run(_cron(), report=[_entry(), _entry(status="scheduled")])

        logged = " ".join(
            str(call) for call in sys.modules["logger"].log.info.call_args_list
        )
        assert "metrics" in logged

    def test_reporting_happens_even_without_a_shelf_life_configured(self):
        import sys

        _run(_cron(secrets={}), report=[_entry()])

        logged = " ".join(
            str(call) for call in sys.modules["logger"].log.info.call_args_list
        )
        assert "metrics" in logged
