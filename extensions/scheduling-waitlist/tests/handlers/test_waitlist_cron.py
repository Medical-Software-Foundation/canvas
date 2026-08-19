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

    def select_related(self, *args):
        return self

    def exclude(self, **kwargs):
        self.exclude_kwargs = kwargs
        return self

    def delete(self):
        self.deleted = True

    def __getitem__(self, item):
        return self.items

    def __iter__(self):
        return iter(self.items)


def _entry(status="waiting", created_days_ago=10, expires_on=None, patient_dbid=1):
    entry = MagicMock()
    entry.status = status
    entry.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    entry.expires_on = expires_on
    entry.patient = MagicMock(dbid=patient_dbid, id=f"uuid-{patient_dbid}")
    return entry


def _ledger(task_id="task-1"):
    """A slot-announcement row with a task still open."""
    row = MagicMock()
    row.task_id = task_id
    row.task_closed_at = None
    return row


def _run(cron, *, missing=None, due=None, report=None, finished=None):
    """Drive the job with a scripted set of query results.

    ``banner_effects`` is stubbed out: these tests are about what the job writes
    to the waitlist, and the banner's own behaviour is covered in
    ``tests/services/test_banner.py``.
    """
    missing_qs = _Queryset(missing or [])
    due_qs = _Queryset(due or [])
    report_qs = _Queryset(report or [])
    notification_qs = _Queryset(finished or [])
    calls = {"n": 0}

    def entry_filter(**kwargs):
        calls["n"] += 1
        if kwargs.get("expires_on__isnull"):
            return missing_qs
        return due_qs

    with (
        patch(f"{MODULE}.WaitlistEntry") as entry_model,
        patch(f"{MODULE}.SlotNotification") as notification_model,
        patch(f"{MODULE}.banner_effects", return_value=[]),
    ):
        entry_model.objects.filter.side_effect = entry_filter
        entry_model.objects.all.return_value = report_qs
        notification_model.objects.filter.return_value = notification_qs
        effects = cron.execute()
        return entry_model, notification_qs, notification_model, effects


class TestSchedule:
    def test_runs_nightly(self):
        assert WaitlistMaintenanceCron.SCHEDULE == "0 3 * * *"


class TestShelfLifeConfiguration:
    def test_nothing_is_aged_out_without_a_configured_shelf_life(self):
        # Expiring entries is destructive; a mistyped setting must not be the
        # reason somebody drops off the list.
        entry_model, _, _, _ = _run(_cron(secrets={}), due=[_entry()])

        entry_model.objects.bulk_update.assert_not_called()

    def test_an_invalid_shelf_life_ages_nothing_out(self):
        entry_model, _, _, _ = _run(
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

        entry_model, _, _, _ = _run(_cron(), due=[entry])

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
        entry_model, _, _, _ = _run(_cron(), due=[])

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
        _, notification_qs, _, _ = _run(_cron())

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


class TestBannerRefresh:
    """Aged-out patients must stop being told they are waiting."""

    def _refresh(self, expired):
        return WaitlistMaintenanceCron._refresh_banners(expired)

    def test_each_aged_out_patient_gets_one_refresh(self):
        expired = [_entry(patient_dbid=1), _entry(patient_dbid=2)]

        with patch(f"{MODULE}.banner_effects", return_value=["b"]) as banner:
            effects = self._refresh(expired)

        assert banner.call_count == 2
        assert effects == ["b", "b"]

    def test_a_patient_with_several_expired_entries_is_refreshed_once(self):
        # The banner is recomputed from what is left, so one call per patient
        # says everything -- and the query it costs is worth paying only once.
        expired = [_entry(patient_dbid=7), _entry(patient_dbid=7)]

        with patch(f"{MODULE}.banner_effects", return_value=["b"]) as banner:
            self._refresh(expired)

        assert banner.call_count == 1

    def test_entries_without_a_patient_are_skipped(self):
        entry = _entry()
        entry.patient = None

        with patch(f"{MODULE}.banner_effects", return_value=["b"]) as banner:
            assert self._refresh([entry]) == []

        banner.assert_not_called()

    def test_nothing_expired_means_no_refreshes(self):
        with patch(f"{MODULE}.banner_effects", return_value=["b"]) as banner:
            assert self._refresh([]) == []

        banner.assert_not_called()

    def test_the_refresh_count_is_capped(self):
        from scheduling_waitlist.constants import MAX_BANNER_REFRESH_PER_RUN

        expired = [
            _entry(patient_dbid=n) for n in range(MAX_BANNER_REFRESH_PER_RUN + 5)
        ]

        with patch(f"{MODULE}.banner_effects", return_value=["b"]) as banner:
            self._refresh(expired)

        assert banner.call_count == MAX_BANNER_REFRESH_PER_RUN

    def test_hitting_the_cap_is_logged_rather_than_passed_over_silently(self):
        from scheduling_waitlist.constants import MAX_BANNER_REFRESH_PER_RUN

        expired = [
            _entry(patient_dbid=n) for n in range(MAX_BANNER_REFRESH_PER_RUN + 1)
        ]

        with (
            patch(f"{MODULE}.banner_effects", return_value=["b"]),
            patch(f"{MODULE}.log") as logger,
        ):
            self._refresh(expired)

        assert logger.warning.called


class TestClosingFinishedTasks:
    """A slot-opened task is dead work once its slot has started.

    Nothing else closes it, so without this the scheduling team's queue grows by
    one for every cancellation, forever, and the live call-lists get lost among
    the finished ones.
    """

    def test_a_task_for_a_passed_slot_is_completed(self):
        _, _, _, effects = _run(_cron(), finished=[_ledger("task-1")])

        assert [e.id for e in effects] == ["task-1"]
        assert effects[0].status == "COMPLETED"

    def test_nothing_finished_closes_nothing(self):
        _, _, _, effects = _run(_cron(), finished=[])

        assert effects == []

    def test_only_slots_that_have_started_are_considered(self):
        _, _, model, _ = _run(_cron(), finished=[_ledger()])

        kwargs = model.objects.filter.call_args.kwargs
        assert "appointment__start_time__lt" in kwargs

    def test_rows_already_closed_are_skipped(self):
        # Otherwise every past slot would be closed again every night, forever.
        _, _, model, _ = _run(_cron(), finished=[_ledger()])

        assert model.objects.filter.call_args.kwargs["task_closed_at__isnull"] is True

    def test_rows_that_never_raised_a_task_are_excluded(self):
        # A slot with no matches records the announcement but has no task id.
        _, qs, _, _ = _run(_cron(), finished=[_ledger()])

        assert qs.exclude_kwargs == {"task_id": ""}

    def test_closing_is_recorded_on_the_ledger(self):
        row = _ledger()

        _, _, model, _ = _run(_cron(), finished=[row])

        assert row.task_closed_at is not None
        assert model.objects.bulk_update.call_args.args[1] == ["task_closed_at"]

    def test_it_runs_even_without_a_shelf_life_configured(self):
        # The two settings are unrelated, and an unconfigured instance is a
        # working instance -- it must not accumulate tasks nobody can act on.
        _, _, _, effects = _run(_cron(secrets={}), finished=[_ledger("task-9")])

        assert [e.id for e in effects] == ["task-9"]

    def test_the_close_is_logged(self):
        import sys

        sys.modules["logger"].log.info.reset_mock()
        _run(_cron(), finished=[_ledger()])

        logged = " ".join(str(c) for c in sys.modules["logger"].log.info.call_args_list)
        assert "closed 1 slot-opened task" in logged

    def test_hitting_the_cap_is_logged_rather_than_passed_over(self):
        import sys
        from scheduling_waitlist.constants import MAX_TASKS_CLOSED_PER_RUN

        sys.modules["logger"].log.warning.reset_mock()
        rows = [_ledger(f"task-{n}") for n in range(MAX_TASKS_CLOSED_PER_RUN)]

        _, _, _, effects = _run(_cron(), finished=rows)

        assert len(effects) == MAX_TASKS_CLOSED_PER_RUN
        assert sys.modules["logger"].log.warning.called
