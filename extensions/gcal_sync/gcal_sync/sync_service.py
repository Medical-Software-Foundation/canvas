"""Core push orchestration shared by the appointment handler and the reconciliation cron.

``SyncService`` owns the upsert/delete logic against Google plus the persistence of the
appointment-id ↔ event-id mapping and the echo-suppression hash. It is deliberately decoupled from
the Canvas event/cron machinery (it takes plain snapshots and ids) and from token minting (a client
factory is injectable) so it can be unit-tested with a fake client.
"""

from collections import defaultdict
from typing import Callable

from logger import log

from gcal_sync.google.auth import GoogleAuth
from gcal_sync.google.client import GoogleApiError, GoogleCalendarClient
from gcal_sync.google.event_builder import (
    CANVAS_APPT_ID_KEY,
    AppointmentSnapshot,
    build_event_body,
    content_hash,
    extract_canvas_appt_id,
)
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

    def push(
        self,
        calendar_id: str,
        snapshot: AppointmentSnapshot,
        mapping_cache: dict[str, AppointmentEventMapping] | None = None,
    ) -> AppointmentEventMapping:
        """Upsert the Google event for an appointment and record the mapping + content hash.

        Insert when we have no event for this appointment yet, otherwise patch in place. Idempotent:
        the unique constraint on ``canvas_appointment_id`` plus ``get`` means a duplicate event
        delivery updates the existing row instead of creating a second event (spec §6.3).

        ``mapping_cache`` lets a batch caller (the reconcile re-push) prefetch every appointment's
        mapping in ONE query and pass it in, so a run over N appointments does 1 mapping query
        instead of N. A missing key means "no mapping exists" (the cache is authoritative for the
        ids it was built from); the real-time handler omits it and falls back to a per-id ``get``.
        """
        appointment_id = str(snapshot["appointment_id"])
        body = build_event_body(snapshot)
        new_hash = content_hash(body)

        mapping = self._resolve_mapping(appointment_id, mapping_cache)

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
            # Idempotency (adopt, don't duplicate): we may have pushed this appointment before and
            # lost the local mapping — an appointment hard-deleted-and-recreated, a dropped mapping
            # row, or a first pass whose mapping write didn't persist. Blindly inserting would create
            # a SECOND event on the provider's calendar. Look for an event we already stamped with
            # this appointment id and patch it in place; only insert when Google truly has none. This
            # is what makes the reconcile safe to re-run after mapping drift.
            existing = client.find_event_by_private_property(
                calendar_id, CANVAS_APPT_ID_KEY, appointment_id
            )
            if existing is not None:
                client.patch_event(calendar_id, existing["id"], body)
                event_id = existing["id"]
            else:
                event_id = client.insert_event(calendar_id, body)["id"]
            # update_or_create (not create) so a stale mapping_cache miss can't collide with an
            # existing row on the unique canvas_appointment_id constraint.
            new_mapping: AppointmentEventMapping = AppointmentEventMapping.objects.update_or_create(
                canvas_appointment_id=appointment_id,
                defaults={
                    "google_calendar_id": calendar_id,
                    "google_event_id": event_id,
                    "last_pushed_hash": new_hash,
                },
            )[0]
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

    def sweep_calendar(
        self,
        calendar_id: str,
        live_appointment_ids: set[str],
        time_min: str,
        time_max: str,
        max_deletes: int,
    ) -> int:
        """Remove events we pushed that shouldn't be on the calendar; collapse duplicates.

        ``live_appointment_ids`` is the authoritative set of appointment ids that SHOULD each have
        exactly one event in this window (the caller computes it from Canvas: enrolled, non-terminal,
        in-window, not Google-origin). Only events WE stamped (``canvasApptId``) are ever touched.
        For each stamped appointment id found on the calendar:
          - not in the live set  -> the appointment was cancelled/deleted/moved out of window; delete
            every event for it and drop its mapping (orphan cleanup);
          - in the live set with >1 event -> keep one (the mapped event when identifiable), delete the
            rest (dedupe).
        Bounded by ``max_deletes`` per call so the blast radius is small if the live set is wrong.
        Returns the number of Google events deleted.
        """
        client = self._client_factory(calendar_id)
        by_appt: dict[str, list[dict]] = defaultdict(list)
        for event in client.list_all_events(calendar_id, time_min, time_max):
            appt_id = extract_canvas_appt_id(event)
            if appt_id:
                by_appt[appt_id].append(event)

        deletes = 0
        for appt_id, events in by_appt.items():
            if deletes >= max_deletes:
                break
            if appt_id not in live_appointment_ids:
                # Orphan: no live in-window appointment backs these events -> remove them + the mapping.
                for event in events:
                    if deletes >= max_deletes:
                        break
                    client.delete_event(calendar_id, event["id"])
                    deletes += 1
                AppointmentEventMapping.objects.filter(
                    canvas_appointment_id=appt_id, google_calendar_id=calendar_id
                ).delete()
            elif len(events) > 1:
                # Duplicate: keep the mapped event if we can identify it, else the first; delete rest.
                mapping = AppointmentEventMapping.objects.filter(
                    canvas_appointment_id=appt_id, google_calendar_id=calendar_id
                ).first()
                ids = {e["id"] for e in events}
                keep = mapping.google_event_id if mapping and mapping.google_event_id in ids else events[0]["id"]
                for event in events:
                    if deletes >= max_deletes:
                        break
                    if event["id"] != keep:
                        client.delete_event(calendar_id, event["id"])
                        deletes += 1
        if deletes:
            log.info("Sweep removed %s stale/duplicate event(s) from %s", deletes, calendar_id)
        return deletes

    def _safe_delete(self, calendar_id: str, event_id: str) -> None:
        client = self._client_factory(calendar_id)
        client.delete_event(calendar_id, event_id)

    def _resolve_mapping(
        self, appointment_id: str, mapping_cache: dict[str, AppointmentEventMapping] | None
    ) -> AppointmentEventMapping | None:
        """Look the mapping up in a prefetched cache when the caller supplied one, else query it.

        The cache is authoritative for the ids it was built from, so a miss means "no mapping" and
        we do NOT fall back to a query (that would re-introduce the per-appointment N+1).
        """
        if mapping_cache is not None:
            return mapping_cache.get(appointment_id)
        return self._existing_mapping(appointment_id)

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
