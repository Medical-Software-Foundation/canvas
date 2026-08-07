"""Nightly housekeeping: age out stale entries and report on the list."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from scheduling_waitlist.constants import (
    MATCHABLE_STATUSES,
    MAX_ENTRIES_EXPIRED_PER_RUN,
    SLOT_NOTIFICATION_RETENTION_DAYS,
    STATUS_EXPIRED,
)
from scheduling_waitlist.models import SlotNotification, WaitlistEntry
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.metrics import format_summary, summarize


class WaitlistMaintenanceCron(CronTask):
    """Runs once a night, at 03:00 UTC."""

    SCHEDULE = "0 3 * * *"

    def execute(self) -> list[Effect]:
        """Backfill expiry dates, age out lapsed entries, prune, and report."""
        config = WaitlistConfig.from_secrets(self.secrets)
        now = datetime.now(timezone.utc)
        today = now.date()

        self._report(today)
        self._prune_notifications(now)

        if config.ttl_days is None:
            # Deliberately not a fallback. Expiring entries is destructive, and
            # a mistyped setting must not be the reason someone drops off the
            # list.
            log.error(
                "scheduling_waitlist: WAITLIST_TTL_DAYS is unset or invalid, so no "
                "entries were aged out"
            )
            return []

        self._backfill_expiry(config.ttl_days, today)
        self._expire_due(today)
        return []

    # -- pieces ----------------------------------------------------------

    @staticmethod
    def _backfill_expiry(ttl_days: int, today: date) -> None:
        """Give an expiry date to entries written without one.

        The schema pipeline emits no column defaults, so rows created before
        this column existed carry nothing and would otherwise never lapse.
        """
        missing = list(
            WaitlistEntry.objects.filter(
                status__in=list(MATCHABLE_STATUSES), expires_on__isnull=True
            )[:MAX_ENTRIES_EXPIRED_PER_RUN]
        )
        if not missing:
            return

        for entry in missing:
            created = getattr(entry, "created_at", None)
            start = created.date() if isinstance(created, datetime) else today
            entry.expires_on = start + timedelta(days=ttl_days)

        WaitlistEntry.objects.bulk_update(missing, ["expires_on"])
        log.info(f"scheduling_waitlist: backfilled expiry on {len(missing)} entries")

    @staticmethod
    def _expire_due(today: date) -> None:
        """Age out entries that have outlived their shelf life.

        A status change rather than a deletion: the wait-time reporting depends
        on these rows, reinstating one should not mean re-keying it, and a job
        that silently deletes staff-entered data is not something to ship.
        """
        due = list(
            WaitlistEntry.objects.filter(
                status__in=list(MATCHABLE_STATUSES), expires_on__lt=today
            ).order_by("expires_on", "dbid")[:MAX_ENTRIES_EXPIRED_PER_RUN]
        )
        if not due:
            return

        now = datetime.now(timezone.utc)
        for entry in due:
            entry.status = STATUS_EXPIRED
            entry.status_reason = "passed the configured shelf life"
            entry.status_changed_at = now
            entry.status_changed_by_id = None

        WaitlistEntry.objects.bulk_update(
            due, ["status", "status_reason", "status_changed_at", "status_changed_by"]
        )
        log.info(f"scheduling_waitlist: aged out {len(due)} entries")

        if len(due) == MAX_ENTRIES_EXPIRED_PER_RUN:
            log.warning(
                "scheduling_waitlist: hit the per-run age-out cap, so more entries are "
                "still due; they will be picked up on the next run"
            )

    @staticmethod
    def _prune_notifications(now: datetime) -> None:
        """Drop old slot-announcement records.

        Pure machine state with no operational value once the slot has passed,
        so this one really is a deletion.
        """
        cutoff = now - timedelta(days=SLOT_NOTIFICATION_RETENTION_DAYS)
        SlotNotification.objects.filter(notified_at__lt=cutoff).delete()

    @staticmethod
    def _report(today: date) -> None:
        """Log how long people are waiting and how often the list pays off."""
        entries = list(WaitlistEntry.objects.all().only("status", "created_at"))
        log.info(format_summary(summarize(entries, today=today)))
