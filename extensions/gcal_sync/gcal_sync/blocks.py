"""Sync provider admin blocks (lunch / PTO / "Blocked" / etc.) from Canvas to Google.

Admin blocks live in a *different* model than appointments: they are
``canvas_sdk.v1.data.calendar.Event`` objects on a provider's **Administrative** calendar(s)
(title = the block's reason), created by the provider-availability plugin. They emit no lifecycle
events, so they sync via a **sweep** (the block cron + "Reconcile now"), not in real time.

Two things keep this correct:
- **Only real blocks sync.** Auto-generated availability artifacts — ``"Buffer"`` and ``"Lead Time"``
  — are excluded by title (configurable via ``EXCLUDED_BLOCK_TITLES``). Clinic "Available" events are
  excluded by construction (we only read Administrative calendars).
- **Cheap when nothing changes.** A block is only written to Google when its content hash changes;
  a removed block is deleted from Google. A steady state makes zero Google calls.

No PHI: a block carries no patient, and only its title/time are sent (via the shared PHI-safe
``build_event_body``).
"""

import arrow
from requests import RequestException

from canvas_sdk.v1.data.calendar import Calendar, Event
from canvas_sdk.v1.data.staff import Staff
from logger import log

from gcal_sync.google.auth import GoogleAuth, GoogleAuthError
from gcal_sync.google.client import GoogleApiError, GoogleCalendarClient
from gcal_sync.google.event_builder import AppointmentSnapshot, build_event_body, content_hash
from gcal_sync.models import CalendarEventMapping
from gcal_sync.sync_service import ClientFactory

# Auto-generated availability artifacts that must NOT sync to Google.
DEFAULT_EXCLUDED_BLOCK_TITLES = {"Buffer", "Lead Time"}


def excluded_block_titles(secrets: dict) -> set[str]:
    """Titles to skip when syncing Administrative-calendar events (default: Buffer, Lead Time)."""
    raw = (secrets.get("EXCLUDED_BLOCK_TITLES") or "").strip()
    if not raw:
        return set(DEFAULT_EXCLUDED_BLOCK_TITLES)
    return {item.strip() for item in raw.split(",") if item.strip()}


def block_snapshot(event: Event) -> AppointmentSnapshot:
    """Build a PHI-safe snapshot from a Calendar ``Event`` block (title + time only)."""
    start = event.starts_at
    if event.ends_at is not None:
        duration = max(1, int((arrow.get(event.ends_at) - arrow.get(start)).total_seconds() // 60))
    else:
        duration = 30
    return {
        "appointment_id": str(event.id),
        "visit_type": event.title or "Blocked",
        "start_time": start,
        "duration_minutes": duration,
        "location": None,
        "meeting_link": None,
        "status": "confirmed",
    }


class BlockSync:
    """Sweeps a provider's admin blocks into Google for one calendar."""

    _WINDOW_BACK_MONTHS = -1
    _WINDOW_FWD_YEARS = 1

    def __init__(self, secrets: dict, client_factory: ClientFactory | None = None) -> None:
        self._excluded = excluded_block_titles(secrets)
        auth = GoogleAuth(secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
        self._client_factory = client_factory or (
            lambda calendar_id: GoogleCalendarClient(auth.get_access_token(calendar_id))
        )

    def sync_provider(self, staff_id: str, calendar_id: str) -> dict:
        """Push current blocks and delete removed ones for one provider. Returns ``{pushed, deleted}``."""
        stats = {"pushed": 0, "deleted": 0}
        current = self._current_blocks(staff_id)
        client = self._client_factory(calendar_id)
        # Prefetch this provider's block mappings in ONE query (keyed exactly by canvas_event_id, the
        # unique key), so the per-block upsert below does no lookup of its own. Without this the sweep
        # runs a CalendarEventMapping.get() per block every 15 minutes.
        mapping_cache = {
            m.canvas_event_id: m
            for m in CalendarEventMapping.objects.filter(canvas_event_id__in=list(current.keys()))
        }
        for event_id, event in current.items():
            self._upsert(client, calendar_id, event_id, event, stats, mapping_cache)
        self._delete_removed(client, calendar_id, set(current.keys()), stats)
        return stats

    def _current_blocks(self, staff_id: str) -> dict:
        """Map of ``event_id -> Event`` for this provider's syncable admin blocks in the window."""
        staff = Staff.objects.filter(id=staff_id).first()
        if staff is None or not staff.full_name:
            return {}
        # Administrative calendars are named "<Provider Name>: Admin …" (matches provider_availability).
        calendar_ids = list(
            Calendar.objects.filter(title__startswith=f"{staff.full_name}: Admin").values_list(
                "id", flat=True
            )
        )
        if not calendar_ids:
            return {}

        window_start = arrow.utcnow().shift(months=self._WINDOW_BACK_MONTHS).datetime
        window_end = arrow.utcnow().shift(years=self._WINDOW_FWD_YEARS).datetime
        events = Event.objects.filter(
            calendar__id__in=calendar_ids,
            is_cancelled=False,
            starts_at__gte=window_start,
            starts_at__lte=window_end,
        )
        result = {}
        for event in events:
            if (event.title or "") in self._excluded:
                continue
            result[str(event.id)] = event
        return result

    def _upsert(
        self,
        client: GoogleCalendarClient,
        calendar_id: str,
        event_id: str,
        event: Event,
        stats: dict,
        mapping_cache: dict[str, CalendarEventMapping],
    ) -> None:
        body = build_event_body(block_snapshot(event))
        new_hash = content_hash(body)
        mapping = mapping_cache.get(event_id)

        if mapping is None:
            created = client.insert_event(calendar_id, body)
            CalendarEventMapping.objects.create(
                canvas_event_id=event_id,
                google_calendar_id=calendar_id,
                google_event_id=created["id"],
                last_pushed_hash=new_hash,
            )
            stats["pushed"] = stats["pushed"] + 1
            return

        if mapping.last_pushed_hash == new_hash and mapping.google_calendar_id == calendar_id:
            return  # unchanged — no Google call

        try:
            client.patch_event(calendar_id, mapping.google_event_id, body)
        except GoogleApiError as exc:
            if exc.status_code not in (404, 410):
                raise
            created = client.insert_event(calendar_id, body)
            mapping.google_event_id = created["id"]
        mapping.google_calendar_id = calendar_id
        mapping.last_pushed_hash = new_hash
        mapping.save()
        stats["pushed"] = stats["pushed"] + 1

    def _delete_removed(
        self, client: GoogleCalendarClient, calendar_id: str, current_ids: set, stats: dict
    ) -> None:
        for mapping in CalendarEventMapping.objects.filter(google_calendar_id=calendar_id):
            if mapping.canvas_event_id in current_ids:
                continue
            # Block no longer exists in Canvas -> remove it from Google.
            client.delete_event(calendar_id, mapping.google_event_id)
            mapping.delete()
            stats["deleted"] = stats["deleted"] + 1


def sync_all_blocks(secrets: dict, mappings: list) -> dict:
    """Sweep admin blocks for every enrolled provider. Returns aggregate ``{pushed, deleted}``."""
    block_sync = BlockSync(secrets)
    totals = {"pushed": 0, "deleted": 0}
    for mapping in mappings:
        try:
            stats = block_sync.sync_provider(mapping.canvas_staff_id, mapping.google_calendar_id)
            totals["pushed"] = totals["pushed"] + stats["pushed"]
            totals["deleted"] = totals["deleted"] + stats["deleted"]
        except (GoogleApiError, GoogleAuthError, RequestException) as exc:
            log.error("Block sweep failed for %s: %s", mapping.google_calendar_id, exc)
    return totals
