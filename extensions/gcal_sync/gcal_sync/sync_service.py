"""Core push orchestration shared by the appointment handler and the reconciliation cron.

``SyncService`` owns the upsert/delete logic against Google plus the persistence of the
appointment-id ↔ event-id mapping and the echo-suppression hash. It is deliberately decoupled from
the Canvas event/cron machinery (it takes plain snapshots and ids) and from token minting (a client
factory is injectable) so it can be unit-tested with a fake client.
"""

from typing import Callable

from gcal_sync.google.auth import GoogleAuth
from gcal_sync.google.client import GoogleApiError, GoogleCalendarClient
from gcal_sync.google.event_builder import AppointmentSnapshot, build_event_body, content_hash
from gcal_sync.models import AppointmentEventMapping

ClientFactory = Callable[[str], GoogleCalendarClient]


class SyncService:
    """Pushes Canvas appointment state into Google and maintains the mapping table."""

    def __init__(
        self, service_account_json: str | None, client_factory: ClientFactory | None = None
    ) -> None:
        self._auth = GoogleAuth(service_account_json)
        # The factory builds a per-calendar client. Overridable in tests to avoid auth/network.
        self._client_factory = client_factory or self._default_client_factory

    def _default_client_factory(self, calendar_id: str) -> GoogleCalendarClient:
        return GoogleCalendarClient(self._auth.get_access_token(calendar_id))

    def push(self, calendar_id: str, snapshot: AppointmentSnapshot) -> AppointmentEventMapping:
        """Upsert the Google event for an appointment and record the mapping + content hash.

        Insert when we have no event for this appointment yet, otherwise patch in place. Idempotent:
        the unique constraint on ``canvas_appointment_id`` plus ``get`` means a duplicate event
        delivery updates the existing row instead of creating a second event (spec §6.3).
        """
        appointment_id = str(snapshot["appointment_id"])
        body = build_event_body(snapshot)
        new_hash = content_hash(body)

        mapping = self._existing_mapping(appointment_id)

        # Change-only: if we already pushed this exact content to this calendar, do nothing. This is
        # what lets the reconcile/cron scale — steady-state cost is O(changes), not O(appointments),
        # and it avoids a redundant Google patch on every event for unchanged appointments.
        if (
            mapping is not None
            and mapping.google_calendar_id == calendar_id
            and mapping.last_pushed_hash == new_hash
        ):
            return mapping

        client = self._client_factory(calendar_id)
        if mapping is None:
            created = client.insert_event(calendar_id, body)
            new_mapping: AppointmentEventMapping = AppointmentEventMapping.objects.create(
                canvas_appointment_id=appointment_id,
                google_calendar_id=calendar_id,
                google_event_id=created["id"],
                last_pushed_hash=new_hash,
            )
            return new_mapping

        # If the calendar changed (provider re-mapped), delete from the old calendar first.
        if mapping.google_calendar_id != calendar_id:
            self._safe_delete(mapping.google_calendar_id, mapping.google_event_id)
            created = client.insert_event(calendar_id, body)
            mapping.google_calendar_id = calendar_id
            mapping.google_event_id = created["id"]
        else:
            # Patch in place, but self-heal if the provider deleted the event in Google: a 404/410
            # means our target is gone, so re-create it to restore Canvas as the source of truth.
            try:
                client.patch_event(calendar_id, mapping.google_event_id, body)
            except GoogleApiError as exc:
                if exc.status_code not in (404, 410):
                    raise
                created = client.insert_event(calendar_id, body)
                mapping.google_event_id = created["id"]

        mapping.last_pushed_hash = new_hash
        mapping.save()
        return mapping

    def remove(self, appointment_id: str) -> bool:
        """Delete the Google event for an appointment and drop the mapping. Returns whether one existed."""
        mapping = self._existing_mapping(str(appointment_id))
        if mapping is None:
            return False
        self._safe_delete(mapping.google_calendar_id, mapping.google_event_id)
        mapping.delete()
        return True

    def _safe_delete(self, calendar_id: str, event_id: str) -> None:
        client = self._client_factory(calendar_id)
        client.delete_event(calendar_id, event_id)

    @staticmethod
    def _existing_mapping(appointment_id: str) -> AppointmentEventMapping | None:
        try:
            mapping: AppointmentEventMapping = AppointmentEventMapping.objects.get(
                canvas_appointment_id=appointment_id
            )
            return mapping
        except AppointmentEventMapping.DoesNotExist:
            return None


__all__ = ["SyncService", "GoogleApiError"]
