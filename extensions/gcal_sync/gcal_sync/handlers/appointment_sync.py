"""Phase 1 — push Canvas appointment changes into Google Calendar (spec §4.2).

Subscribes only to the specific appointment lifecycle events (never the broad ``PATIENT_UPDATED`` or
any plugin-lifecycle event), so an unrelated change never triggers this handler. Providers who have
no active staff→calendar mapping are silently skipped — sync is opt-in per provider.

This handler makes an outbound Google API call and persists the appointment↔event mapping; it returns
no Canvas effects (the side effect is the external write, which is the whole point of a sync handler).
"""

from typing import Callable

from requests import RequestException

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from logger import log

from gcal_sync.appointment_snapshot import build_snapshot, google_origin_event_id
from gcal_sync.google.auth import GoogleAuthError
from gcal_sync.google.client import GoogleApiError
from gcal_sync.models import StaffCalendarMapping
from gcal_sync.sync_service import SyncService

# Events that mean "this appointment exists and its details may have changed" -> upsert in Google.
_UPSERT_EVENTS = {
    EventType.APPOINTMENT_CREATED,
    EventType.APPOINTMENT_UPDATED,
    EventType.APPOINTMENT_RESTORED,
    EventType.APPOINTMENT_CHECKED_IN,
}
# Events that mean "this appointment is no longer on the books" -> remove from Google.
_DELETE_EVENTS = {
    EventType.APPOINTMENT_CANCELED,
    EventType.APPOINTMENT_NO_SHOWED,
}


class AppointmentSyncHandler(BaseHandler):
    """On appointment lifecycle events, mirror the appointment into the provider's Google Calendar."""

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_UPDATED),
        EventType.Name(EventType.APPOINTMENT_RESTORED),
        EventType.Name(EventType.APPOINTMENT_CHECKED_IN),
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    ]

    def compute(self) -> list[Effect]:
        appointment_id = self.event.target.id

        if self.event.type in _DELETE_EVENTS:
            self._safe(lambda: self._handle_delete(appointment_id), appointment_id)
            return []

        if self.event.type in _UPSERT_EVENTS:
            self._safe(lambda: self._handle_upsert(appointment_id), appointment_id)
        return []

    def _handle_delete(self, appointment_id: str) -> None:
        # Delete is keyed off the stored mapping, so it works even if the appointment row is gone.
        SyncService(self.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")).remove(appointment_id)

    def _handle_upsert(self, appointment_id: str) -> None:
        if google_origin_event_id(appointment_id):
            # This Canvas record was created FROM a Google event; the Google event already exists, so
            # pushing it back would duplicate it (loop suppression for inbound-originated holds).
            return

        result = build_snapshot(appointment_id)
        if result is None:
            # Retracted (entered-in-error), vanished, or provider-less — treat like a removal so
            # Google doesn't retain an appointment Canvas no longer considers valid.
            SyncService(self.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")).remove(appointment_id)
            return

        snapshot, provider_id, is_schedule_event = result
        if is_schedule_event:
            # Schedule events (admin holds, incl. ones we just imported FROM Google) are NOT pushed
            # on this real-time path: the "came from Google" tag is written a beat after creation, so
            # checking it here races and let inbound holds bounce back to Google. The reconcile sweep
            # handles schedule events later, when that tag is reliably readable. (Canvas-created admin
            # events still sync — just on the reconcile cadence, not instantly.)
            return

        mapping = StaffCalendarMapping.objects.filter(
            canvas_staff_id=provider_id, active=True
        ).first()
        if mapping is None:
            # Provider isn't enrolled in Google sync — nothing to do.
            return

        SyncService(self.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")).push(
            mapping.google_calendar_id, snapshot
        )

    @staticmethod
    def _safe(action: Callable[[], None], appointment_id: str) -> None:
        """Run a sync action, catching only the errors a Google call is expected to raise.

        Unexpected exceptions are allowed to propagate to Sentry (CLAUDE.md: don't swallow bugs).
        """
        try:
            action()
        except (GoogleApiError, GoogleAuthError, RequestException) as exc:
            log.error("Google Calendar sync failed for appointment %s: %s", appointment_id, exc)
