"""Reconciliation logic shared by ``ReconciliationCron`` and the admin "reconcile now" action.

Kept as plain functions (no CronTask/SimpleAPI coupling) so both the scheduled job and the admin API
call exactly the same code path.
"""

import arrow
from django.db import IntegrityError
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
from gcal_sync.inbound import InboundSync
from gcal_sync.models import (
    AppointmentEventMapping,
    CalendarSyncState,
    InboundEventMapping,
    PendingHoldCreate,
    ProviderSyncLock,
    ReimportQueue,
    StaffCalendarMapping,
)
from gcal_sync.sync_service import SyncService

# Statuses that mean "not on the books" — handled by delete events, never reconciled as upserts.
_TERMINAL_STATUSES = {"cancelled", "noshowed"}

# A per-provider admin action (Reconcile / Re-import) holds this lock so a double-click or a second
# admin can't run the same provider concurrently (the buttons run synchronously and can land on
# different plugin-runner containers). A lock older than the TTL is stale — a run that died before
# releasing — and is reclaimed so a provider never wedges.
_PROVIDER_LOCK_TTL_MINUTES = 15


def acquire_provider_lock(calendar_id: str) -> bool:
    """Atomically claim the per-provider action lock. Returns ``False`` if one is already held.

    Acquisition is atomic via the unique ``google_calendar_id`` constraint: a duplicate insert
    raises ``IntegrityError``, which means someone else holds it. A lock past the TTL is reclaimed
    first so a crashed run doesn't wedge the provider forever.
    """
    ProviderSyncLock.objects.filter(
        google_calendar_id=calendar_id,
        acquired_at__lt=arrow.utcnow()
        .shift(minutes=-_PROVIDER_LOCK_TTL_MINUTES)
        .datetime,
    ).delete()
    try:
        ProviderSyncLock.objects.create(google_calendar_id=calendar_id)
        return True
    except IntegrityError:
        return False


def release_provider_lock(calendar_id: str) -> None:
    """Release the per-provider action lock (safe to call even if it was already reclaimed)."""
    ProviderSyncLock.objects.filter(google_calendar_id=calendar_id).delete()


# A first-time / recovery full pull imports a provider's whole 6-month window at once (hundreds of
# holds). Bound how many run in a single reconcile so the bulk path — the nightly cron AND the
# "Reconcile now" button, which share this code — never tries to apply a whole fleet's first import
# in one pass. Cheap delta pulls (calendars with a live sync token) are NEVER capped; deferred full
# pulls are picked up by later runs, least-recently-synced first, so coverage rotates and completes.
_MAX_FULL_PULLS_PER_RUN = 5

# Outbound backfill is bounded per run so one reconcile can't monopolise a worker for hours (or get
# killed mid-run). The idempotent, change-only push makes re-runs safe and resumable: an already
# synced appointment is skipped for free, so successive runs advance through the backlog. Providers
# are processed least-recently-synced first (``last_outbound_synced_at``) so a capped run rotates.
_MAX_OUTBOUND_PUSHES_PER_RUN = 2000

# The fleet reconcile enumerates a provider's Google calendar to remove orphaned/duplicate events.
# That is one full calendar listing per provider, so only this many providers are swept per fleet
# run (least-recently-synced first); the rest rotate in on later runs. A single-provider admin
# reconcile always sweeps that provider. Deletes are additionally capped for a small blast radius.
_MAX_SWEEP_CALENDARS_PER_RUN = 10
_MAX_SWEEP_DELETES_PER_CALENDAR = 500


def _outbound_window() -> tuple:
    """The [-1 month, +1 year] window the outbound sync maintains, as arrow objects."""
    return arrow.utcnow().shift(months=-1), arrow.utcnow().shift(years=1)


def _rfc3339(when) -> str:
    return when.format("YYYY-MM-DD[T]HH:mm:ss[Z]")


def _google_origin_ids() -> set:
    """Appointment ids we imported FROM Google — never pushed back (loop suppression). One query."""
    return set(
        AppointmentExternalIdentifier.objects.filter(
            system=GOOGLE_ORIGIN_SYSTEM
        ).values_list("appointment__id", flat=True)
    )


def _pushable_appointments(
    mapping, window_start, window_end, google_origin_ids: set
) -> list[dict]:
    """The provider's appointments that should each have exactly one Google event in the window."""
    appts = Appointment.objects.filter(
        provider__id=mapping.canvas_staff_id,
        entered_in_error__isnull=True,
        start_time__gte=window_start,
        start_time__lte=window_end,
    ).values(*APPOINTMENT_FIELDS)
    return [
        appt
        for appt in appts
        if appt.get("status") not in _TERMINAL_STATUSES
        and appt.get("id") not in google_origin_ids
    ]


def _outbound_priority(mapping) -> tuple:
    """Sort key: providers never fully synced (null) first, then least-recently-synced."""
    ts = getattr(mapping, "last_outbound_synced_at", None)
    return (0, 0.0) if ts is None else (1, ts.timestamp())


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
    inbound = InboundSync(secrets)
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
            len(delta_ids),
            len(selected_full),
            deferred,
            max_full_pulls,
        )

    effects: list = []
    for calendar_id in delta_ids + selected_full:
        try:
            _stats, calendar_effects = inbound.process_calendar(calendar_id)
            effects.extend(calendar_effects)
        except (
            GoogleApiError,
            GoogleAuthError,
            RequestException,
            ChannelConfigError,
        ) as exc:
            log.error("Reconcile inbound pull failed for %s: %s", calendar_id, exc)
    return effects


def outbound_truth(secrets: dict, mappings: list, max_pushes: int | None = None) -> int:
    """Push every upcoming, non-terminal Canvas appointment for each enrolled provider to Google.

    Bounded and resumable: at most ``max_pushes`` actual Google writes per run (``None`` = unbounded,
    e.g. a single-provider admin reconcile). Providers are processed least-recently-synced first, and
    a provider is stamped ``last_outbound_synced_at`` only once its whole window is processed — so a
    capped run rotates across the fleet and successive runs converge. The change-only guard skips
    already-synced appointments for free, so re-running is cheap and safe. Returns pushes performed.
    """
    sync = SyncService(secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
    start, end = _outbound_window()
    google_origin_ids = _google_origin_ids()

    total_pushed = 0
    for mapping in sorted(mappings, key=_outbound_priority):
        if max_pushes is not None and total_pushed >= max_pushes:
            break
        pushable = _pushable_appointments(
            mapping, start.datetime, end.datetime, google_origin_ids
        )
        # Prefetch this provider's mappings in ONE query so the per-appointment push does no lookup
        # of its own (avoids an N+1 a busy provider would pay on every reconcile).
        mapping_cache = {
            m.canvas_appointment_id: m
            for m in AppointmentEventMapping.objects.filter(
                canvas_appointment_id__in=[str(appt["id"]) for appt in pushable]
            )
        }
        completed = True
        for appt in pushable:
            if max_pushes is not None and total_pushed >= max_pushes:
                completed = False  # ran out of budget mid-provider -> retry it next run
                break
            try:
                sync.push(
                    mapping.google_calendar_id,
                    snapshot_from_values(appt),
                    mapping_cache,
                )
                total_pushed += 1
            except (GoogleApiError, GoogleAuthError, RequestException) as exc:
                log.error(
                    "Reconcile push failed for appt %s -> %s: %s",
                    appt.get("id"),
                    mapping.google_calendar_id,
                    exc,
                )
        if completed and hasattr(mapping, "last_outbound_synced_at"):
            mapping.last_outbound_synced_at = arrow.utcnow().datetime
            try:
                mapping.save()
            except Exception:
                # Bookkeeping only — never let a failed timestamp save abort the reconcile.
                log.exception(
                    "Could not record last_outbound_synced_at for %s",
                    mapping.canvas_staff_id,
                )
    return total_pushed


def sweep_outbound(
    secrets: dict, mappings: list, max_calendars: int | None = None
) -> int:
    """Remove orphaned/duplicate Google events for the given providers. Returns events deleted.

    Enumerates each provider's calendar (one listing per provider), so the fleet run only sweeps the
    ``max_calendars`` least-recently-synced providers per run — the rest rotate in later. A
    single-provider admin reconcile passes ``None`` to always sweep that one provider.
    """
    sync = SyncService(secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
    start, end = _outbound_window()
    start_rfc, end_rfc = _rfc3339(start), _rfc3339(end)
    google_origin_ids = _google_origin_ids()

    selected = sorted(mappings, key=_outbound_priority)
    if max_calendars is not None:
        selected = selected[:max_calendars]

    total_deleted = 0
    for mapping in selected:
        pushable = _pushable_appointments(
            mapping, start.datetime, end.datetime, google_origin_ids
        )
        live_ids = {str(appt["id"]) for appt in pushable}
        try:
            total_deleted += sync.sweep_calendar(
                mapping.google_calendar_id,
                live_ids,
                start_rfc,
                end_rfc,
                _MAX_SWEEP_DELETES_PER_CALENDAR,
            )
        except (GoogleApiError, GoogleAuthError, RequestException) as exc:
            log.error(
                "Reconcile sweep failed for %s: %s", mapping.google_calendar_id, exc
            )
    return total_deleted


def reconcile_provider(
    secrets: dict, mapping: StaffCalendarMapping
) -> tuple[dict, list]:
    """Reconcile a SINGLE provider (inbound delta + change-only outbound push + block sweep).

    Per-provider so the admin button never does all providers in one request (chunking for scale).
    """
    effects: list = []
    inbound = InboundSync(secrets)
    try:
        _stats, calendar_effects = inbound.process_calendar(mapping.google_calendar_id)
        effects.extend(calendar_effects)
    except (
        GoogleApiError,
        GoogleAuthError,
        RequestException,
        ChannelConfigError,
    ) as exc:
        log.error(
            "Reconcile (provider) inbound failed for %s: %s",
            mapping.google_calendar_id,
            exc,
        )

    pushed = outbound_truth(secrets, [mapping])
    # Single-provider admin reconcile: always sweep this provider's calendar for orphaned/duplicate
    # events (max_calendars=None), the thorough per-provider cleanup an admin reaches for.
    swept = sweep_outbound(secrets, [mapping], max_calendars=None)
    blocks = sync_all_blocks(secrets, [mapping])
    return (
        {
            "pushed": pushed,
            "swept": swept,
            "blocks_pushed": blocks["pushed"],
            "blocks_deleted": blocks["deleted"],
        },
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
    effects: list[Effect] = [
        ScheduleEvent(instance_id=str(i)).delete() for i in hold_ids
    ]
    InboundEventMapping.objects.filter(
        google_calendar_id=mapping.google_calendar_id
    ).delete()
    # Clear pending-create markers too, so the rebuild that follows isn't skipped as "in flight".
    PendingHoldCreate.objects.filter(
        google_calendar_id=mapping.google_calendar_id
    ).delete()
    return effects


def purge_holds_chunk(
    mapping: StaffCalendarMapping, limit: int, after_id: str = ""
) -> tuple[list[Effect], str, bool]:
    """Cancel up to ``limit`` of a provider's non-cancelled Google-origin holds in one bounded request.

    Ordered by appointment id and resumed via the ``after_id`` cursor, so an admin can drain a heavy
    provider across many small, fast calls instead of one request that exceeds the gateway timeout.
    Returns ``(cancel_effects, last_id, done)``; ``done`` is True on the final chunk, which also drops
    the provider's ``InboundEventMapping`` rows. The cursor advances by id regardless of when the
    async cancels apply, so every hold is covered exactly once and the loop converges deterministically.
    """
    qs = AppointmentExternalIdentifier.objects.filter(
        system=GOOGLE_ORIGIN_SYSTEM,
        appointment__provider__id=mapping.canvas_staff_id,
    ).exclude(appointment__status="cancelled")
    if after_id:
        qs = qs.filter(appointment__id__gt=after_id)
    ids = list(
        qs.order_by("appointment__id")
        .values_list("appointment__id", flat=True)
        .distinct()[:limit]
    )
    effects: list[Effect] = [ScheduleEvent(instance_id=str(i)).delete() for i in ids]
    done = len(ids) < limit
    if done:
        InboundEventMapping.objects.filter(
            google_calendar_id=mapping.google_calendar_id
        ).delete()
        PendingHoldCreate.objects.filter(
            google_calendar_id=mapping.google_calendar_id
        ).delete()
    last_id = str(ids[-1]) if ids else after_id
    return effects, last_id, done


def reimport_provider(
    secrets: dict,
    mapping: StaffCalendarMapping,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[dict, list]:
    """Force a full re-pull of one provider's Google calendar, rebuilding holds from what's there now.

    Non-destructive: clears the stored sync token and does a full ``force_rebuild`` pull so it ADOPTS
    the provider's current live holds (updating them in place) and recreates any that are missing or
    were cancelled — without cancelling the provider's holds first. The full pull returns ALL current
    events (not just changes since the last token); ``force_rebuild`` bypasses the convergence guard
    so a hold whose only prior copy was cancelled is recreated. To deliberately REMOVE a provider's
    holds, use Purge — not Re-import.

    ``dry_run`` previews what a re-import would do without any side effects: the sync token is left
    untouched, no mapping rows are written, and the returned effects are discarded by the caller. Use
    it to confirm a re-import would fill the right gaps and never double a live hold before running it
    for real (see ``scripts/dry_run_holds.py``).

    ``verbose`` logs a per-event line for each outcome (single-provider re-import). The fleet pass
    leaves it ``False`` so a whole-roster rebuild logs only per-provider summaries.
    """
    if not dry_run:
        state, _ = CalendarSyncState.objects.get_or_create(
            google_calendar_id=mapping.google_calendar_id
        )
        state.sync_token = ""
        state.needs_full_resync = True
        state.save()

    inbound = InboundSync(secrets)
    stats, effects = inbound.process_calendar(
        mapping.google_calendar_id, force_rebuild=True, dry_run=dry_run, verbose=verbose
    )
    log.info(
        "Re-import%s for %s: %s",
        " (dry-run)" if dry_run else "",
        mapping.google_calendar_id,
        stats,
    )
    return stats, effects


# How many queued providers one drain-cron tick re-imports. Each provider is a full-window pull
# (~1-2k events, a few hundred hold effects), so a small batch keeps a tick well under the worker
# task time limit and bounds the effects applied per invocation. The rest drain on later ticks.
_REIMPORT_DRAIN_BATCH = 4

# A queued provider whose re-import keeps raising is dropped after this many attempts so one broken
# calendar (e.g. access revoked) can't wedge the drain — logged so the failure is visible.
_MAX_REIMPORT_ATTEMPTS = 3


def enqueue_fleet_reimport(limit: int | None = None) -> int:
    """Queue every active provider for a re-import. Idempotent; returns how many rows were newly added.

    Fast, synchronous DB writes only — no Google calls — so the "Re-import all" request returns at
    once and ``ReimportDrainCron`` does the actual rebuilds a few providers per tick. A provider
    already queued (from an earlier click or an in-flight drain) is left as-is rather than doubled.
    ``limit`` is a test/escape-hatch cap; ``None`` = the whole active roster.
    """
    mappings = StaffCalendarMapping.objects.filter(active=True).order_by(
        "google_calendar_id"
    )
    if limit is not None:
        mappings = mappings[:limit]
    queued = 0
    for mapping in mappings:
        _obj, created = ReimportQueue.objects.get_or_create(
            google_calendar_id=mapping.google_calendar_id
        )
        if created:
            queued = queued + 1
    return queued


def reimport_queue_depth() -> int:
    """How many providers are still waiting in (or mid-) the fleet re-import queue."""
    return int(ReimportQueue.objects.count())


def cancel_fleet_reimport() -> int:
    """Empty the re-import queue so the drain cron stops rebuilding. Returns how many rows were cleared.

    The cancel lever for a fleet re-import that is straining the instance: once the queue is empty,
    ``ReimportDrainCron`` no-ops. A tick already mid-flight finishes its small current batch (those
    rows are gone, so it picks up nothing new). Holds already rebuilt are untouched — cancel only
    stops further work. Idempotent (clearing an empty queue is a no-op).
    """
    cleared = reimport_queue_depth()
    ReimportQueue.objects.all().delete()
    return cleared


def drain_reimport_queue(
    secrets: dict, batch_size: int = _REIMPORT_DRAIN_BATCH
) -> tuple[dict, list]:
    """Re-import up to ``batch_size`` queued providers, one lock each. Returns ``(totals, effects)``.

    The per-tick body of the fleet re-import. Oldest-queued first, each under the same per-provider
    lock the admin buttons use so a manual re-import and the drain never run the same provider at
    once. A provider is deleted from the queue only once its re-import succeeds; a busy (locked) one
    is left for the next tick, and a repeatedly-failing one is dropped after ``_MAX_REIMPORT_ATTEMPTS``.
    A queued provider whose mapping has since been removed/deactivated is dropped. Effects are
    returned for the cron to apply — a small batch per tick, small enough that the platform applies
    it reliably (a whole-roster batch is too large to apply as one blob).
    """
    entries = list(ReimportQueue.objects.order_by("enqueued_at")[:batch_size])
    totals = {
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "dropped": 0,
        "holds_created": 0,
        "holds_updated": 0,
        "holds_unchanged": 0,
        "holds_removed": 0,
        "remaining": 0,
    }
    effects: list = []
    for entry in entries:
        calendar_id = entry.google_calendar_id
        mapping = StaffCalendarMapping.objects.filter(
            google_calendar_id=calendar_id, active=True
        ).first()
        if mapping is None:
            # Provider was deactivated or unmapped after being queued — nothing to rebuild.
            totals["dropped"] = totals["dropped"] + 1
            entry.delete()
            continue
        if not acquire_provider_lock(calendar_id):
            # A manual action or an overlapping tick holds it; leave queued for the next tick.
            totals["skipped"] = totals["skipped"] + 1
            continue
        try:
            stats, eff = reimport_provider(secrets, mapping)
            effects.extend(eff)
            totals["processed"] = totals["processed"] + 1
            for key in (
                "holds_created",
                "holds_updated",
                "holds_unchanged",
                "holds_removed",
            ):
                totals[key] = totals[key] + stats.get(key, 0)
            entry.delete()
        except (
            GoogleApiError,
            GoogleAuthError,
            RequestException,
            ChannelConfigError,
        ) as exc:
            totals["failed"] = totals["failed"] + 1
            entry.attempts = entry.attempts + 1
            if entry.attempts >= _MAX_REIMPORT_ATTEMPTS:
                entry.delete()
                totals["dropped"] = totals["dropped"] + 1
                log.error(
                    "Re-import drain: dropping %s after %s failed attempt(s): %s",
                    calendar_id,
                    entry.attempts,
                    exc,
                )
            else:
                entry.save()
                log.error(
                    "Re-import drain: %s failed (attempt %s), will retry: %s",
                    calendar_id,
                    entry.attempts,
                    exc,
                )
        finally:
            release_provider_lock(calendar_id)

    totals["remaining"] = reimport_queue_depth()
    if entries:
        log.info(
            "Re-import drain: %s rebuilt, %s created, %s busy, %s failed, %s dropped, %s remaining",
            totals["processed"],
            totals["holds_created"],
            totals["skipped"],
            totals["failed"],
            totals["dropped"],
            totals["remaining"],
        )
    return totals, effects


def reconcile_all(secrets: dict) -> tuple[dict, list]:
    """Full reconcile across all active mappings. Returns ``(stats, hold_effects)``."""
    mappings = list(StaffCalendarMapping.objects.filter(active=True))
    if not mappings:
        return {"mappings": 0, "pushed": 0, "blocks_pushed": 0, "blocks_deleted": 0}, []
    effects = inbound_recovery(secrets, mappings)
    pushed = outbound_truth(secrets, mappings, max_pushes=_MAX_OUTBOUND_PUSHES_PER_RUN)
    swept = sweep_outbound(
        secrets, mappings, max_calendars=_MAX_SWEEP_CALENDARS_PER_RUN
    )
    blocks = sync_all_blocks(secrets, mappings)
    log.info(
        "Reconciliation complete: %s mapping(s), %s appt(s) pushed, %s stale event(s) swept, "
        "%s block(s) pushed/%s deleted",
        len(mappings),
        pushed,
        swept,
        blocks["pushed"],
        blocks["deleted"],
    )
    return (
        {
            "mappings": len(mappings),
            "pushed": pushed,
            "swept": swept,
            "blocks_pushed": blocks["pushed"],
            "blocks_deleted": blocks["deleted"],
        },
        effects,
    )
