"""Google → Canvas delta processing: the safety-critical half of two-way sync.

When a watch channel pings the webhook, we pull the incremental delta for that calendar and decide,
per changed event, what it means for Canvas:

1. **Echo suppression (§6.1).** Events we pushed carry ``extendedProperties.private.canvasApptId``
   and we remember the content hash. An inbound event whose hash still matches is our own write
   coming back — dropped.

2. **Appointments stay Canvas-owned (§6.2).** A genuine provider-side change to a Canvas *appointment*
   is reverted (re-push Canvas truth); actually mutating the appointment from Google is gated behind
   an empty-by-default allow-list because it is a patient-safety hazard.

3. **New Google events become admin holds.** An unmarked event (created by the provider in Google) is
   imported into Canvas as a schedule event (admin hold) blocking their availability. This is safe —
   no patient, no scheduling-rule risk. Edits/removals of those holds flow back too.

4. **410 recovery (§6.4).** An invalid sync token clears the cursor and flags a full resync.

Effects (hold create/update/delete) are returned to the caller (the webhook / cron) to apply.
"""

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.v1.data.appointment import AppointmentExternalIdentifier
from logger import log

from gcal_sync.appointment_snapshot import GOOGLE_ORIGIN_SYSTEM, build_snapshot
from gcal_sync.google.client import GoogleApiError
from gcal_sync.inbound_holds import (
    PRIVATE_EVENT_LABEL,
    build_hold_effect,
    ingest_all_day_events,
    ingest_private_events,
    is_all_day,
    is_private,
    parse_event_window,
    provider_and_location,
    schedule_event_note_type_id,
)
from gcal_sync.google.event_builder import extract_canvas_appt_id, google_event_content_hash
from gcal_sync.models import AppointmentEventMapping, CalendarSyncState, InboundEventMapping
from gcal_sync.sync_service import ClientFactory, SyncService


class InboundSync:
    """Processes one calendar's incremental delta from Google."""

    _FULL_PULL_TIME_MIN_SHIFT_MONTHS = -1
    # Forward bound: only import the next 6 months of (recurring) events. Without this, a daily
    # recurring event expands into thousands of holds (we once hit year 2040 / ~37k holds). This
    # window — NOT the cap below — is the real guard against unbounded recurring expansion.
    _FULL_PULL_TIME_MAX_SHIFT_MONTHS = 6
    # Runaway backstop: a single run creating more holds than this for one provider means something is
    # broken (the 2040 bug was ~37k). Set high enough to comfortably import a dense provider's full
    # 6-month calendar — hundreds of recurring-meeting instances is normal and expected here.
    _MAX_HOLDS_PER_RUN = 5000
    # The create effect is applied asynchronously, so a mapping written moments ago still has no
    # visible Canvas hold. Within this window we treat the mapping as a create in flight and skip
    # re-importing the event; re-issuing the create here is what generated duplicate holds under
    # load. Past the window, a still-holdless mapping is a genuine orphan and is re-created.
    _PENDING_CREATE_GRACE_SECONDS = 30 * 60

    def __init__(
        self,
        secrets: dict,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._secrets = secrets or {}
        self._sync = SyncService(
            self._secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON"), client_factory=client_factory
        )
        self._client_factory = self._sync._client_factory
        self._ingest_private = ingest_private_events(self._secrets)
        self._ingest_all_day = ingest_all_day_events(self._secrets)
        # Cache of (calendar_id, note_type_id, provider_id, location_id). The note type and the
        # provider/location are identical for every event in a calendar's pull, so we resolve them
        # ONCE per calendar instead of re-querying per imported event. Re-resolved when the calendar
        # changes (one InboundSync instance processes calendars sequentially in reconcile).
        self._import_ctx: tuple[str, str | None, str | None, str | None] | None = None

    def _import_context(self, calendar_id: str) -> tuple[str | None, str | None, str | None]:
        """Resolve (note_type_id, provider_id, location_id) for ``calendar_id``, cached per calendar."""
        if self._import_ctx is None or self._import_ctx[0] != calendar_id:
            note_type_id = schedule_event_note_type_id(self._secrets)
            resolved = provider_and_location(calendar_id)
            provider_id, location_id = resolved if resolved else (None, None)
            self._import_ctx = (calendar_id, note_type_id, provider_id, location_id)
        return self._import_ctx[1], self._import_ctx[2], self._import_ctx[3]

    def process_calendar(self, calendar_id: str) -> tuple[dict, list[Effect]]:
        """Pull and apply the delta for ``calendar_id``. Returns ``(stats, effects)``."""
        state, _ = CalendarSyncState.objects.get_or_create(google_calendar_id=calendar_id)
        client = self._client_factory(calendar_id)

        use_token = state.sync_token and not state.needs_full_resync
        stats: dict = {
            "processed": 0,
            "echoes": 0,
            "reverted": 0,
            "holds_created": 0,
            "holds_updated": 0,
            "holds_removed": 0,
            "ignored": 0,
            "full_resync": False,
            "capped": False,
        }
        effects: list[Effect] = []

        try:
            events, next_token = client.list_event_deltas(
                calendar_id,
                sync_token=state.sync_token if use_token else "",
                time_min="" if use_token else self._full_pull_time_min(),
                time_max="" if use_token else self._full_pull_time_max(),
            )
        except GoogleApiError as exc:
            if exc.status_code == 410:
                log.warning("syncToken for %s is gone (410); scheduling full resync", calendar_id)
                state.sync_token = ""
                state.needs_full_resync = True
                state.save()
                stats["full_resync"] = True
                return stats, effects
            raise

        for event in events:
            effects.extend(self._apply(calendar_id, event, stats))
            if stats["holds_created"] >= self._MAX_HOLDS_PER_RUN:
                # Circuit breaker: abort without advancing the sync cursor so we don't snowball.
                log.error(
                    "Inbound safety cap (%s) hit for %s — aborting run. Something is wrong.",
                    self._MAX_HOLDS_PER_RUN,
                    calendar_id,
                )
                stats["capped"] = True
                return stats, effects

        if next_token:
            state.sync_token = next_token
        state.needs_full_resync = False
        state.save()
        return stats, effects

    def _full_pull_time_min(self) -> str:
        return (
            arrow.utcnow()
            .shift(months=self._FULL_PULL_TIME_MIN_SHIFT_MONTHS)
            .format("YYYY-MM-DD[T]HH:mm:ss[Z]")
        )

    def _full_pull_time_max(self) -> str:
        return (
            arrow.utcnow()
            .shift(months=self._FULL_PULL_TIME_MAX_SHIFT_MONTHS)
            .format("YYYY-MM-DD[T]HH:mm:ss[Z]")
        )

    def _apply(self, calendar_id: str, event: dict, stats: dict) -> list[Effect]:
        """Decide and act on a single changed Google event. Returns any Canvas effects to apply."""
        stats["processed"] = stats["processed"] + 1
        appt_id = extract_canvas_appt_id(event)

        if appt_id:
            self._handle_marked_event(calendar_id, appt_id, event, stats)
            return []

        # Unmarked: a provider-created Google event -> admin-hold territory (Google -> Canvas).
        return self._handle_unmarked_event(calendar_id, event, stats)

    def _handle_marked_event(self, calendar_id: str, appt_id: str, event: dict, stats: dict) -> None:
        """An event carrying our canvasApptId stamp — our own push echoing back, or a provider edit."""
        mapping = AppointmentEventMapping.objects.filter(canvas_appointment_id=appt_id).first()
        if mapping is None:
            stats["ignored"] = stats["ignored"] + 1
            return

        if event.get("status") != "cancelled" and google_event_content_hash(event) == mapping.last_pushed_hash:
            stats["echoes"] = stats["echoes"] + 1
            return

        # Genuine provider-side change to a Canvas appointment: revert to Canvas truth (Canvas wins).
        result = build_snapshot(appt_id)
        if result is None:
            self._sync.remove(appt_id)
        else:
            snapshot, _provider_id, _is_schedule_event = result
            self._sync.push(calendar_id, snapshot)
        stats["reverted"] = stats["reverted"] + 1

    def _handle_unmarked_event(self, calendar_id: str, event: dict, stats: dict) -> list[Effect]:
        """A provider-created Google event -> create/update/delete the corresponding Canvas hold."""
        google_event_id = event.get("id")
        if not google_event_id:
            stats["ignored"] = stats["ignored"] + 1
            return []

        existing = InboundEventMapping.objects.filter(google_event_id=google_event_id).first()
        status = event.get("status")

        if status == "cancelled":
            if existing is None:
                stats["ignored"] = stats["ignored"] + 1
                return []
            effect = self._hold_delete_effect(google_event_id)
            existing.delete()
            stats["holds_removed"] = stats["holds_removed"] + 1
            return [effect] if effect else []

        # A mapping row alone does NOT prove a Canvas hold exists: the create effect is applied
        # asynchronously, so a run that was interrupted or hit the safety cap can leave a mapping
        # with no appointment behind it. Only take the UPDATE path when a live hold actually
        # exists; otherwise fall through and (re)create it so partial prior runs self-heal.
        if existing is not None and self._canvas_id_for_google_event(google_event_id) is not None:
            effect = self._hold_update_effect(google_event_id, event)
            if effect is None:
                stats["ignored"] = stats["ignored"] + 1
                return []
            stats["holds_updated"] = stats["holds_updated"] + 1
            return [effect]

        # Mapping exists but no live hold (the update branch above didn't fire). The create is
        # applied asynchronously, so a recently-recorded mapping is a create still in flight —
        # re-issuing it is what produced duplicate holds under load. Skip while pending; only fall
        # through to re-create once the mapping predates the grace window (a genuine orphan).
        if existing is not None:
            created_at = getattr(existing, "created_at", None)
            if created_at is None or (
                (arrow.utcnow() - arrow.get(created_at)).total_seconds()
                < self._PENDING_CREATE_GRACE_SECONDS
            ):
                stats["ignored"] = stats["ignored"] + 1
                return []

        # Brand-new Google event (or a genuine orphan past the grace window) -> create a Canvas
        # admin hold, subject to the org's import filters.
        if is_all_day(event) and not self._ingest_all_day:
            stats["ignored"] = stats["ignored"] + 1
            return []
        if is_private(event) and not self._ingest_private:
            stats["ignored"] = stats["ignored"] + 1
            return []

        note_type_id, provider_id, location_id = self._import_context(calendar_id)
        effect = build_hold_effect(event, note_type_id, provider_id, location_id)
        if effect is None:
            stats["ignored"] = stats["ignored"] + 1
            return []
        # Record synchronously so a re-delivered webhook doesn't import it twice. Upsert rather than
        # create: an orphaned mapping row for this event id may already exist (google_event_id is
        # unique), and re-creating the hold must not collide with it.
        InboundEventMapping.objects.update_or_create(
            google_event_id=google_event_id,
            defaults={"google_calendar_id": calendar_id},
        )
        stats["holds_created"] = stats["holds_created"] + 1
        return [effect]

    @staticmethod
    def _canvas_id_for_google_event(google_event_id: str) -> str | None:
        """Resolve the Canvas record id for an imported Google event via its external identifier."""
        canvas_id = (
            AppointmentExternalIdentifier.objects.filter(
                system=GOOGLE_ORIGIN_SYSTEM, value=google_event_id
            )
            .values_list("appointment__id", flat=True)
            .first()
        )
        return str(canvas_id) if canvas_id else None

    def _hold_delete_effect(self, google_event_id: str) -> Effect | None:
        canvas_id = self._canvas_id_for_google_event(google_event_id)
        if not canvas_id:
            return None
        return ScheduleEvent(instance_id=str(canvas_id)).delete()

    def _hold_update_effect(self, google_event_id: str, event: dict) -> Effect | None:
        canvas_id = self._canvas_id_for_google_event(google_event_id)
        if not canvas_id:
            return None
        window = parse_event_window(event)
        if window is None:
            return None
        start_time, duration_minutes = window
        schedule_event = ScheduleEvent(instance_id=str(canvas_id))
        schedule_event.start_time = start_time
        schedule_event.duration_minutes = duration_minutes
        # Mask private/confidential titles on UPDATE too, not just on create — otherwise editing a
        # private Google event would overwrite the "Busy" placeholder with its real (PHI-adjacent)
        # title in Canvas.
        if is_private(event):
            schedule_event.description = PRIVATE_EVENT_LABEL
        else:
            schedule_event.description = (event.get("summary") or "Busy")[:255]
        return schedule_event.update()
