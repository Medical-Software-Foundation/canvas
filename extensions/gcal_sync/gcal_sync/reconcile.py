"""Reconciliation logic shared by ``ReconciliationCron`` and the admin "reconcile now" action.

Kept as plain functions (no CronTask/SimpleAPI coupling) so both the scheduled job and the admin API
call exactly the same code path.
"""

import arrow
from requests import RequestException

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.v1.data.appointment import Appointment, AppointmentExternalIdentifier
from logger import log

from gcal_sync.appointment_snapshot import (
    APPOINTMENT_FIELDS,
    GOOGLE_ORIGIN_SYSTEM,
    snapshot_from_values,
)
from gcal_sync.blocks import sync_all_blocks
from gcal_sync.channels import ChannelConfigError
from gcal_sync.google.auth import GoogleAuthError
from gcal_sync.google.client import GoogleApiError
from gcal_sync.inbound import InboundSync, allowed_google_changes
from gcal_sync.models import CalendarSyncState, InboundEventMapping, StaffCalendarMapping
from gcal_sync.sync_service import SyncService

# Statuses that mean "not on the books" — handled by delete events, never reconciled as upserts.
_TERMINAL_STATUSES = {"cancelled", "noshowed"}

# A first-time / recovery full pull imports a provider's whole 6-month window at once (hundreds of
# holds). Bound how many run in a single reconcile so the bulk path — the nightly cron AND the
# "Reconcile now" button, which share this code — never tries to apply a whole fleet's first import
# in one pass. Cheap delta pulls (calendars with a live sync token) are NEVER capped; deferred full
# pulls are picked up by later runs, least-recently-synced first, so coverage rotates and completes.
_MAX_FULL_PULLS_PER_RUN = 5


def _needs_full_pull(state: CalendarSyncState | None) -> bool:
    """A calendar with no sync token (never synced) or flagged for resync needs an expensive pull."""
    return state is None or not state.sync_token or state.needs_full_resync


def _full_pull_priority(state: CalendarSyncState | None) -> tuple[int, str]:
    """Sort key: never-synced calendars first, then least-recently-synced, so deferrals rotate in."""
    if state is None:
        return (0, "")
    updated = getattr(state, "updated_at", None)
    return (1, updated.isoformat() if updated else "")


def inbound_recovery(
    secrets: dict, mappings: list, max_full_pulls: int = _MAX_FULL_PULLS_PER_RUN
) -> list:
    """Run a delta pull per calendar so an invalidated syncToken recovers. Returns hold effects.

    Expensive first-time / recovery full pulls are capped at ``max_full_pulls`` per run; the rest are
    deferred to later runs so one reconcile never floods Canvas with an entire fleet's first import.
    Cheap delta pulls are always run.
    """
    inbound = InboundSync(secrets, allowed_changes=allowed_google_changes(secrets))
    calendar_ids = {m.google_calendar_id for m in mappings}
    states = {
        s.google_calendar_id: s
        for s in CalendarSyncState.objects.filter(google_calendar_id__in=calendar_ids)
    }

    delta_ids = [c for c in calendar_ids if not _needs_full_pull(states.get(c))]
    full_ids = sorted(
        (c for c in calendar_ids if _needs_full_pull(states.get(c))),
        key=lambda c: _full_pull_priority(states.get(c)),
    )
    selected_full = full_ids[:max_full_pulls]
    deferred = len(full_ids) - len(selected_full)
    if deferred:
        log.info(
            "Reconcile: %s delta pull(s), %s full pull(s) this run, %s full pull(s) deferred (cap %s).",
            len(delta_ids), len(selected_full), deferred, max_full_pulls,
        )

    effects: list = []
    for calendar_id in delta_ids + selected_full:
        try:
            _stats, calendar_effects = inbound.process_calendar(calendar_id)
            effects.extend(calendar_effects)
        except (GoogleApiError, GoogleAuthError, RequestException, ChannelConfigError) as exc:
            log.error("Reconcile inbound pull failed for %s: %s", calendar_id, exc)
    return effects


def outbound_truth(secrets: dict, mappings: list) -> int:
    """Re-push every upcoming, non-cancelled Canvas appointment for each enrolled provider.

    Returns the number of appointments successfully pushed.
    """
    sync = SyncService(secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
    window_start = arrow.utcnow().shift(months=-1).datetime
    window_end = arrow.utcnow().shift(years=1).datetime

    # Records we imported from Google must not be pushed back (loop suppression). One query.
    google_origin_ids = set(
        AppointmentExternalIdentifier.objects.filter(system=GOOGLE_ORIGIN_SYSTEM).values_list(
            "appointment__id", flat=True
        )
    )

    total_pushed = 0
    for mapping in mappings:
        appts = Appointment.objects.filter(
            provider__id=mapping.canvas_staff_id,
            entered_in_error__isnull=True,
            start_time__gte=window_start,
            start_time__lte=window_end,
        ).values(*APPOINTMENT_FIELDS)
        for appt in appts:
            if appt.get("status") in _TERMINAL_STATUSES:
                continue
            if appt.get("id") in google_origin_ids:
                continue
            try:
                sync.push(mapping.google_calendar_id, snapshot_from_values(appt))
                total_pushed += 1
            except (GoogleApiError, GoogleAuthError, RequestException) as exc:
                log.error(
                    "Reconcile push failed for appt %s -> %s: %s",
                    appt.get("id"),
                    mapping.google_calendar_id,
                    exc,
                )
    return total_pushed


def reconcile_provider(secrets: dict, mapping: StaffCalendarMapping) -> tuple[dict, list]:
    """Reconcile a SINGLE provider (inbound delta + change-only outbound push + block sweep).

    Per-provider so the admin button never does all providers in one request (chunking for scale).
    """
    effects: list = []
    inbound = InboundSync(secrets, allowed_changes=allowed_google_changes(secrets))
    try:
        _stats, calendar_effects = inbound.process_calendar(mapping.google_calendar_id)
        effects.extend(calendar_effects)
    except (GoogleApiError, GoogleAuthError, RequestException, ChannelConfigError) as exc:
        log.error("Reconcile (provider) inbound failed for %s: %s", mapping.google_calendar_id, exc)

    pushed = outbound_truth(secrets, [mapping])
    blocks = sync_all_blocks(secrets, [mapping])
    return (
        {"pushed": pushed, "blocks_pushed": blocks["pushed"], "blocks_deleted": blocks["deleted"]},
        effects,
    )


def reset_inbound_for_provider(mapping: StaffCalendarMapping) -> list[Effect]:
    """Wipe a provider's imported state so a re-import can rebuild it cleanly from scratch.

    Cancels the provider's existing (non-cancelled) Google-origin holds and drops the
    ``InboundEventMapping`` rows for the calendar. Without this, a re-import can't recreate holds that
    were cancelled out-of-band (e.g. by the cleanup cron) — their mapping still exists, so the pull
    would only *update* the cancelled record instead of bringing the event back — and clearing the
    mapping without cancelling the live holds would create duplicates. Returns the cancel effects.
    """
    hold_ids = list(
        AppointmentExternalIdentifier.objects.filter(
            system=GOOGLE_ORIGIN_SYSTEM,
            appointment__provider__id=mapping.canvas_staff_id,
        )
        .exclude(appointment__status="cancelled")
        .values_list("appointment__id", flat=True)
        .distinct()
    )
    effects: list[Effect] = [ScheduleEvent(instance_id=str(i)).delete() for i in hold_ids]
    InboundEventMapping.objects.filter(google_calendar_id=mapping.google_calendar_id).delete()
    return effects


def reimport_provider(secrets: dict, mapping: StaffCalendarMapping) -> tuple[dict, list]:
    """Force a clean full re-pull of one provider's Google calendar, importing every event as a hold.

    Resets the provider's imported state (cancels existing holds, drops inbound mappings) and clears
    the stored sync token so ``events.list`` returns ALL current events (not just changes since the
    last token). This is how *pre-existing* Google events get imported and how a provider whose holds
    were wiped gets rebuilt from scratch. Troubleshooting / re-baseline aid.
    """
    reset_effects = reset_inbound_for_provider(mapping)

    state, _ = CalendarSyncState.objects.get_or_create(google_calendar_id=mapping.google_calendar_id)
    state.sync_token = ""
    state.needs_full_resync = True
    state.save()

    inbound = InboundSync(secrets, allowed_changes=allowed_google_changes(secrets))
    stats, effects = inbound.process_calendar(mapping.google_calendar_id)
    log.info("Re-import for %s: %s", mapping.google_calendar_id, stats)
    return stats, reset_effects + effects


def reconcile_all(secrets: dict) -> tuple[dict, list]:
    """Full reconcile across all active mappings. Returns ``(stats, hold_effects)``."""
    mappings = list(StaffCalendarMapping.objects.filter(active=True))
    if not mappings:
        return {"mappings": 0, "pushed": 0, "blocks_pushed": 0, "blocks_deleted": 0}, []
    effects = inbound_recovery(secrets, mappings)
    pushed = outbound_truth(secrets, mappings)
    blocks = sync_all_blocks(secrets, mappings)
    log.info(
        "Reconciliation complete: %s mapping(s), %s appt(s) pushed, %s block(s) pushed/%s deleted",
        len(mappings), pushed, blocks["pushed"], blocks["deleted"],
    )
    return (
        {
            "mappings": len(mappings),
            "pushed": pushed,
            "blocks_pushed": blocks["pushed"],
            "blocks_deleted": blocks["deleted"],
        },
        effects,
    )
