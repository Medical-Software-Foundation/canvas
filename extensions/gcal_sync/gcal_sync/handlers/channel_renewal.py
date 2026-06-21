"""Daily renewal of Google ``events.watch`` channels before they expire (spec §6.4).

If a channel lapses, Google→Canvas push notifications silently stop. This cron renews every active
provider calendar's channel that is missing or within the renewal window, recreating it. A failure
on one calendar is logged and does not abort the others.
"""

from requests import RequestException

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from gcal_sync.channels import ChannelConfigError, ChannelManager
from gcal_sync.google.auth import GoogleAuthError
from gcal_sync.google.client import GoogleApiError
from gcal_sync.models import StaffCalendarMapping


class ChannelRenewalCron(CronTask):
    """Renews watch channels for all actively-synced calendars once a day."""

    SCHEDULE = "0 6 * * *"

    def execute(self) -> list[Effect]:
        try:
            manager = ChannelManager(self.secrets)
        except ChannelConfigError as exc:
            # No webhook config yet (sync not provisioned) — nothing to renew.
            log.info("Channel renewal skipped: %s", exc)
            return []

        renewed = 0
        for calendar_id in _active_calendar_ids():
            try:
                if manager.renew_if_needed(calendar_id):
                    renewed += 1
            except (GoogleApiError, GoogleAuthError, RequestException, ChannelConfigError) as exc:
                log.error("Failed to renew watch channel for %s: %s", calendar_id, exc)

        log.info("Channel renewal complete: %s channel(s) renewed", renewed)
        return []


def _active_calendar_ids() -> list[str]:
    return list(
        StaffCalendarMapping.objects.filter(active=True)
        .values_list("google_calendar_id", flat=True)
        .distinct()
    )
