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
   no patient, no scheduling-rule risk. Edits/removals of those holds flow back too. An **all-day**
   event becomes one hold **per covered day** (Canvas blocks a hold's date of service only, so a
   single multi-day hold would leave every day after the first bookable); the covered set is
   reconciled on every pull, so extending, shortening, or deleting the Google event adds and removes
   the matching per-day holds.

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
    ALL_DAY_DURATION_MINUTES,
    all_day_dates,
    build_hold_effect,
    hold_external_id,
    hold_title,
    ingest_all_day_events,
    ingest_private_events,
    is_all_day,
    is_private,
    parse_event_window,
    provider_and_location,
    schedule_event_note_type_id,
)
from gcal_sync.google.event_builder import (
    extract_canvas_appt_id,
    google_event_content_hash,
)
from gcal_sync.models import (
    AppointmentEventMapping,
    CalendarSyncState,
    InboundEventMapping,
    PendingHoldCreate,
)
from gcal_sync.sync_service import ClientFactory, SyncService


# Cap the dry-run trace so a very large calendar can't bloat the response.
_MAX_TRACE = 500


def _event_line(event: dict) -> str:
    """A short, non-persisted one-liner for the dry-run preview: when + (masked) title.

    Private/confidential events show the same ``Busy`` placeholder the imported hold would, so a
    real (PHI-adjacent) title never surfaces even in the preview.
    """
    window = parse_event_window(event)
    when = arrow.get(window[0]).format("ddd MMM DD HH:mm") if window else "(no start)"
    return f"{when} \u2014 {hold_title(event)[:60]}"


def _dry_trace(stats: dict, outcome: str, event: dict) -> None:
    """Append a preview line to ``stats['trace']`` when a dry run is collecting one (else a no-op)."""
    trace = stats.get("trace")
    if trace is None:
        return
    if len(trace) < _MAX_TRACE:
        trace.append(f"{outcome}: {_event_line(event)}")
    elif len(trace) == _MAX_TRACE:
        trace.append(f"\u2026 (preview capped at {_MAX_TRACE} events)")


def _event_log(
    verbose: bool, outcome: str, calendar_id: str, provider_id: str | None, gid: str
) -> None:
    """Emit a title-free per-event log line — only when ``verbose`` (a single-provider re-import).

    Bulk and steady-state paths pass ``verbose=False`` and log only the per-calendar summary, so a
    fleet re-import or a routine webhook never floods the logs with one line per event.
    """
    if verbose:
        log.info(
            "gcal inbound: %s calendar=%s provider=%s event=%s",
            outcome,
            calendar_id,
            provider_id,
            gid,
        )


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
            self._secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON"),
            client_factory=client_factory,
        )
        self._client_factory = self._sync._client_factory
        self._ingest_private = ingest_private_events(self._secrets)
        self._ingest_all_day = ingest_all_day_events(self._secrets)
        # Cache of (calendar_id, note_type_id, provider_id, location_id). The note type and the
        # provider/location are identical for every event in a calendar's pull, so we resolve them
        # ONCE per calendar instead of re-querying per imported event. Re-resolved when the calendar
        # changes (one InboundSync instance processes calendars sequentially in reconcile).
        self._import_ctx: tuple[str, str | None, str | None, str | None] | None = None

    def _import_context(
        self, calendar_id: str
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve (note_type_id, provider_id, location_id) for ``calendar_id``, cached per calendar."""
        if self._import_ctx is None or self._import_ctx[0] != calendar_id:
            note_type_id = schedule_event_note_type_id(self._secrets)
            resolved = provider_and_location(calendar_id)
            provider_id, location_id = resolved if resolved else (None, None)
            self._import_ctx = (calendar_id, note_type_id, provider_id, location_id)
        return self._import_ctx[1], self._import_ctx[2], self._import_ctx[3]

    def process_calendar(
        self,
        calendar_id: str,
        force_rebuild: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> tuple[dict, list[Effect]]:
        """Pull and apply the delta for ``calendar_id``. Returns ``(stats, effects)``.

        ``force_rebuild`` is the deliberate admin "Re-import" path: it bypasses the convergence guard
        so events whose only hold is cancelled are re-created. Every other caller (webhook, reconcile)
        leaves it ``False`` so the routine steady state can never re-create a cancelled hold.

        ``dry_run`` computes exactly the same create/update/skip decisions but makes NO side effects:
        no mapping-table writes, no Google writes, and the sync token is not advanced. It also pulls
        the FULL window (ignoring any stored token) so it previews the same thing a real re-import
        does — a real re-import clears the token to force a full pull, which dry_run can't persist, so
        without this a dry run would do a near-empty delta pull and preview almost nothing. The
        returned effects are what WOULD be applied — the caller inspects ``stats`` and discards them.
        """
        state, _ = CalendarSyncState.objects.get_or_create(
            google_calendar_id=calendar_id
        )
        client = self._client_factory(calendar_id)

        # A dry run always does a full-window pull (never a delta) so its preview matches a real
        # re-import; the real re-import gets the full pull by clearing the token, which dry_run won't do.
        use_token = state.sync_token and not state.needs_full_resync and not dry_run
        stats: dict = {
            "processed": 0,
            "echoes": 0,
            "reverted": 0,
            "holds_created": 0,
            "holds_updated": 0,
            "holds_unchanged": 0,
            "holds_removed": 0,
            "ignored": 0,
            "full_resync": False,
            "capped": False,
        }
        if dry_run:
            stats["trace"] = []
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
                log.warning(
                    "syncToken for %s is gone (410); scheduling full resync",
                    calendar_id,
                )
                state.sync_token = ""
                state.needs_full_resync = True
                if not dry_run:
                    state.save()
                stats["full_resync"] = True
                return stats, effects
            raise

        for event in events:
            effects.extend(
                self._apply(calendar_id, event, stats, force_rebuild, dry_run, verbose)
            )
            if stats["holds_created"] >= self._MAX_HOLDS_PER_RUN:
                # Circuit breaker: abort without advancing the sync cursor so we don't snowball.
                log.error(
                    "Inbound safety cap (%s) hit for %s — aborting run. Something is wrong.",
                    self._MAX_HOLDS_PER_RUN,
                    calendar_id,
                )
                stats["capped"] = True
                return stats, effects

        if not dry_run:
            if next_token:
                state.sync_token = next_token
            state.needs_full_resync = False
            state.save()
        log.info(
            "gcal inbound %s%s: processed=%s created=%s updated=%s unchanged=%s removed=%s ignored=%s",
            calendar_id,
            " (dry-run)" if dry_run else "",
            stats["processed"],
            stats["holds_created"],
            stats["holds_updated"],
            stats["holds_unchanged"],
            stats["holds_removed"],
            stats["ignored"],
        )
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

    def _apply(
        self,
        calendar_id: str,
        event: dict,
        stats: dict,
        force_rebuild: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[Effect]:
        """Decide and act on a single changed Google event. Returns any Canvas effects to apply."""
        stats["processed"] = stats["processed"] + 1
        appt_id = extract_canvas_appt_id(event)

        if appt_id:
            self._handle_marked_event(
                calendar_id, appt_id, event, stats, dry_run, verbose
            )
            return []

        # Unmarked: a provider-created Google event -> admin-hold territory (Google -> Canvas).
        return self._handle_unmarked_event(
            calendar_id, event, stats, force_rebuild, dry_run, verbose
        )

    def _handle_marked_event(
        self,
        calendar_id: str,
        appt_id: str,
        event: dict,
        stats: dict,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        """An event carrying our canvasApptId stamp — our own push echoing back, or a provider edit."""
        mapping = AppointmentEventMapping.objects.filter(
            canvas_appointment_id=appt_id
        ).first()
        if mapping is None:
            stats["ignored"] = stats["ignored"] + 1
            return

        if (
            event.get("status") != "cancelled"
            and google_event_content_hash(event) == mapping.last_pushed_hash
        ):
            stats["echoes"] = stats["echoes"] + 1
            return

        # Genuine provider-side change to a Canvas appointment: revert to Canvas truth (Canvas wins).
        _dry_trace(stats, "would re-push Canvas appointment", event)
        _event_log(verbose, "re-push Canvas appointment", calendar_id, "", appt_id)
        stats["reverted"] = stats["reverted"] + 1
        if dry_run:
            return
        result = build_snapshot(appt_id)
        if result is None:
            self._sync.remove(appt_id)
        else:
            snapshot, _provider_id, _is_schedule_event = result
            self._sync.push(calendar_id, snapshot)

    def _handle_unmarked_event(
        self,
        calendar_id: str,
        event: dict,
        stats: dict,
        force_rebuild: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[Effect]:
        """A provider-created Google event -> create/update/delete the corresponding Canvas hold."""
        google_event_id = event.get("id")
        if not google_event_id:
            stats["ignored"] = stats["ignored"] + 1
            return []

        # Resolve this calendar's provider up front so every hold lookup below is scoped to it. A
        # shared multi-attendee Google event carries the SAME id on every attendee's calendar, so an
        # unscoped lookup finds another provider's hold and wrongly skips this one — the reason a
        # provider's shared meetings never imported. (Note type / location come from the same cached
        # resolve and are reused by the create path.)
        note_type_id, provider_id, location_id = self._import_context(calendar_id)

        # InboundEventMapping holds the last-applied content hash for the no-op guard. It is unique per
        # google_event_id (shared across a shared event's attendees), which is fine for a content hash
        # (identical on every calendar). Scope the read to this calendar so a row owned by another
        # attendee doesn't feed this provider a stale hash.
        existing = InboundEventMapping.objects.filter(
            google_event_id=google_event_id, google_calendar_id=calendar_id
        ).first()
        # PendingHoldCreate is the per-(calendar, event) "create in flight" marker. Unlike the shared
        # InboundEventMapping row, it is keyed per calendar, so a co-attendee's calendar can't clobber
        # this one — which is what stops a webhook replay from minting a second hold for this provider
        # while the create is still applying.
        pending = PendingHoldCreate.objects.filter(
            google_event_id=google_event_id, google_calendar_id=calendar_id
        ).first()
        status = event.get("status")

        if status == "cancelled":
            # Remove only THIS provider's holds for the event (scoped); another attendee's hold for
            # the same shared event id is left untouched. Plural because an all-day event expands
            # into one hold per covered day — a cancellation delta carries no start/end, so we can't
            # recompute the dates and instead remove every hold stamped with this event id.
            effects = self._hold_delete_effects(google_event_id, provider_id)
            if not dry_run:
                if existing is not None:
                    existing.delete()
                # Clear this calendar's pending marker so a later legitimate re-create of the event
                # isn't wrongly treated as still-in-flight.
                if pending is not None:
                    pending.delete()
            if not effects:
                stats["ignored"] = stats["ignored"] + 1
                return []
            _dry_trace(stats, "would remove hold", event)
            _event_log(
                verbose, "remove hold", calendar_id, provider_id, google_event_id
            )
            stats["holds_removed"] = stats["holds_removed"] + len(effects)
            return effects

        # Bounded window. A delta pull (any calendar with a sync token) carries no ``timeMax``, so
        # Google's ``singleEvents`` expansion returns a recurring event's instances with NO upper
        # bound (we have imported instances dated to year 2099). The full-pull window is only applied
        # on the FIRST pull; this per-event guard is what actually keeps recurring expansion bounded
        # on every subsequent delta. Deletes are handled above so a hold that drifts out of window
        # can still be removed.
        if not self._within_import_window(event):
            _dry_trace(stats, "skip (outside 6-month import window)", event)
            _event_log(
                verbose,
                "skip (outside import window)",
                calendar_id,
                provider_id,
                google_event_id,
            )
            stats["ignored"] = stats["ignored"] + 1
            return []

        # All-day events are the multi-day case. Canvas blocks a hold's date of service and nothing
        # after it, so one hold carrying a 5-day duration leaves days 2..5 bookable — a provider
        # could be booked straight through their PTO. Reconcile a SET of per-day holds instead of a
        # single hold; that branch owns create, update and stale-day removal together, because one
        # Google edit routinely needs all three in the same pass.
        dates = all_day_dates(event)
        if dates:
            return self._reconcile_all_day_holds(
                calendar_id,
                event,
                dates,
                existing,
                pending,
                note_type_id,
                provider_id,
                location_id,
                stats,
                force_rebuild,
                dry_run,
                verbose,
            )

        # A live Canvas hold already exists for this event -> update it in place, never create a
        # second one. Keyed on the external id (Canvas's own record), so this holds even if the
        # ``InboundEventMapping`` row was lost — a mapping-less live hold used to fall through to
        # create and duplicate.
        if self._canvas_id_for_google_event(google_event_id, provider_id) is not None:
            # No-op guard: a delta routinely re-delivers unchanged events, and a webhook that times
            # out before advancing the sync token makes the SAME delta re-pull on every ping. Re-issuing
            # an UPDATE for a hold whose content hasn't moved re-saves its appointment row for nothing —
            # a large share of the appointment-table write load. Skip when the content hash matches what
            # we last applied (mirrors the outbound push's change-only guard).
            new_hash = google_event_content_hash(event)
            # A live hold can exist without a mapping row (the mapping is only advisory here), so read
            # the last-applied hash defensively — no mapping means "nothing applied yet" -> update.
            last_applied = (
                existing.last_applied_hash if existing is not None else ""
            ) or ""
            if new_hash == last_applied:
                _dry_trace(stats, "already current (no change)", event)
                _event_log(
                    verbose,
                    "already current (no change)",
                    calendar_id,
                    provider_id,
                    google_event_id,
                )
                stats["holds_unchanged"] = stats["holds_unchanged"] + 1
                return []
            effect = self._hold_update_effect(google_event_id, event, provider_id)
            if effect is None:
                stats["ignored"] = stats["ignored"] + 1
                return []
            # Record the applied hash so an unchanged re-delivery is recognized next time. Upsert (not
            # filter().update()) so a mapping-less live hold gets its row (re)created and the no-op
            # guard self-heals.
            if not dry_run:
                InboundEventMapping.objects.update_or_create(
                    google_event_id=google_event_id,
                    defaults={
                        "google_calendar_id": calendar_id,
                        "last_applied_hash": new_hash,
                    },
                )
            _dry_trace(stats, "would update hold", event)
            _event_log(
                verbose, "update hold", calendar_id, provider_id, google_event_id
            )
            stats["holds_updated"] = stats["holds_updated"] + 1
            return [effect]

        # Convergence guard: a hold was already created for this event but is no longer live — it was
        # cancelled, either because Google deleted the event (handled above on a later delta) or
        # because the purge drained it. ``ScheduleEvent`` has no revive, so re-creating it is exactly
        # the create -> cancel -> re-create loop that minted 260k cancelled duplicate holds. One
        # Google event maps to at most one Canvas hold for its whole life: leave the cancelled hold
        # cancelled and do not mint another — unless this is a deliberate rebuild (admin re-import),
        # which explicitly wants a drained provider's holds recreated.
        if not force_rebuild and self._external_hold_exists(
            google_event_id, provider_id
        ):
            _dry_trace(
                stats,
                "skip (prior hold for this provider was cancelled/drained)",
                event,
            )
            _event_log(
                verbose,
                "skip (convergence: prior hold cancelled/drained)",
                calendar_id,
                provider_id,
                google_event_id,
            )
            stats["ignored"] = stats["ignored"] + 1
            return []

        # No live hold exists for this (provider, event). A pending marker for THIS calendar means the
        # create is applied asynchronously and still in flight — re-issuing within the grace window is
        # what produced duplicate holds under load. Skip while pending; only fall through to (re)create
        # once the marker predates the grace window (a genuine orphan whose create never applied) so
        # partial prior runs self-heal. The marker is per (calendar, event), so a co-attendee syncing
        # the same shared event can't clear it out from under this provider.
        if self._create_in_flight(pending):
            _dry_trace(stats, "skip (create already in flight)", event)
            _event_log(
                verbose, "skip (create in flight)", calendar_id, provider_id, google_event_id
            )
            stats["ignored"] = stats["ignored"] + 1
            return []

        # Brand-new Google event (or a genuine orphan past the grace window) -> create a Canvas
        # admin hold, subject to the org's import filters. All-day events are handled by the
        # reconcile branch above, so this one only catches an all-day event whose dates wouldn't
        # parse (``all_day_dates`` returned empty).
        if is_all_day(event) and not self._ingest_all_day:
            _dry_trace(stats, "skip (all-day event, not imported)", event)
            _event_log(
                verbose,
                "skip (all-day event)",
                calendar_id,
                provider_id,
                google_event_id,
            )
            stats["ignored"] = stats["ignored"] + 1
            return []
        if is_private(event) and not self._ingest_private:
            _dry_trace(stats, "skip (private event, not imported)", event)
            _event_log(
                verbose,
                "skip (private event)",
                calendar_id,
                provider_id,
                google_event_id,
            )
            stats["ignored"] = stats["ignored"] + 1
            return []

        effect = build_hold_effect(event, note_type_id, provider_id, location_id)
        if effect is None:
            _dry_trace(
                stats,
                "skip (could not build hold: unparseable time / no note type)",
                event,
            )
            _event_log(
                verbose,
                "skip (could not build hold)",
                calendar_id,
                provider_id,
                google_event_id,
            )
            stats["ignored"] = stats["ignored"] + 1
            return []
        # Record synchronously so a re-delivered webhook doesn't import it twice. The per-(calendar,
        # event) PendingHoldCreate marker is the dedup that must not be clobbered by a co-attendee's
        # calendar; its created_at is refreshed each attempt so a past-grace re-create gets a fresh
        # window. InboundEventMapping stores the content hash for the no-op guard (event id unique;
        # the hash is identical across a shared event's attendees, so a shared row is fine).
        if not dry_run:
            PendingHoldCreate.objects.update_or_create(
                google_event_id=google_event_id,
                google_calendar_id=calendar_id,
                defaults={"created_at": arrow.utcnow().datetime},
            )
            InboundEventMapping.objects.update_or_create(
                google_event_id=google_event_id,
                defaults={
                    "google_calendar_id": calendar_id,
                    "last_applied_hash": google_event_content_hash(event),
                },
            )
        _dry_trace(stats, "would import hold", event)
        _event_log(verbose, "create hold", calendar_id, provider_id, google_event_id)
        stats["holds_created"] = stats["holds_created"] + 1
        return [effect]

    def _reconcile_all_day_holds(
        self,
        calendar_id: str,
        event: dict,
        dates: list[str],
        existing: InboundEventMapping | None,
        pending: PendingHoldCreate | None,
        note_type_id: str | None,
        provider_id: str | None,
        location_id: str | None,
        stats: dict,
        force_rebuild: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[Effect]:
        """Make this provider's holds for an all-day event match exactly the days it covers.

        Canvas blocks a hold's date of service and nothing after it, so a multi-day all-day event
        needs one hold per day. This reconciles the whole set in one pass: create the covered days
        that have no hold, update the ones that do, and remove holds for days the event no longer
        covers (the provider shortened or moved the PTO).

        Per-day holds are keyed ``{event_id}:{date}``. A hold carrying the **bare** event id predates
        this expansion, so it is adopted as the first covered day rather than duplicated — that is
        what keeps an already-imported single-day event from gaining a second hold.
        """
        google_event_id = event["id"]
        if not provider_id:
            # Unmapped calendar: every hold lookup below is scoped to the provider, so there is
            # nothing to resolve, update, or create.
            stats["ignored"] = stats["ignored"] + 1
            return []
        live = self._live_holds_for_event(google_event_id, provider_id)

        # Map each live hold onto the day it covers. A hold that lands on no covered day (the event
        # shrank or moved), or on a day already covered (a pre-expansion hold plus its per-day
        # replacement), is stale and gets removed.
        live_by_date: dict[str, str] = {}
        stale: list[str] = []
        for value, canvas_id in sorted(live.items()):
            date = dates[0] if value == google_event_id else value.split(":", 1)[1]
            if date in dates and date not in live_by_date:
                live_by_date[date] = canvas_id
            else:
                stale.append(canvas_id)

        # No-op guard. Unlike the single-hold path, an unchanged content hash is not enough: the set
        # of days must also already be complete, or a hold left over from before this fix (one hold,
        # five days) would match on hash and the missing days would never be created.
        new_hash = google_event_content_hash(event)
        last_applied = (existing.last_applied_hash if existing is not None else "") or ""
        content_changed = new_hash != last_applied
        missing = [date for date in dates if date not in live_by_date]
        if not content_changed and not missing and not stale:
            _dry_trace(stats, "already current (no change)", event)
            _event_log(
                verbose,
                "already current (no change)",
                calendar_id,
                provider_id,
                google_event_id,
            )
            stats["holds_unchanged"] = stats["holds_unchanged"] + 1
            return []

        # Creates are the dedup-sensitive part: a re-delivered webhook must not mint a second hold
        # while a previous pass's create is still applying. Updates and removals are idempotent, so
        # the in-flight marker gates only the creates — and a partially-created set finishes itself
        # once the marker ages past the grace window.
        if missing and self._create_in_flight(pending):
            _dry_trace(stats, "skip (create already in flight)", event)
            _event_log(
                verbose, "skip (create in flight)", calendar_id, provider_id, google_event_id
            )
            stats["ignored"] = stats["ignored"] + 1
            return []

        # Import filters gate NEW holds only. An org that turns all-day ingest off keeps the holds it
        # already has in sync (and can still have them removed) rather than stranding them. Each
        # filter logs its reason and empties ``missing``; the event is counted as ignored once at the
        # bottom, and only if the pass ends up with nothing to do at all.
        if missing and not self._ingest_all_day:
            _dry_trace(stats, "skip (all-day event, not imported)", event)
            _event_log(
                verbose, "skip (all-day event)", calendar_id, provider_id, google_event_id
            )
            missing = []
        if missing and not (note_type_id and location_id):
            # No note type or no primary practice location — a hold cannot be built for any day, so
            # say so once rather than failing the same way once per covered day.
            _dry_trace(stats, "skip (could not build hold: no note type / location)", event)
            _event_log(
                verbose, "skip (could not build hold)", calendar_id, provider_id, google_event_id
            )
            missing = []
        if missing and is_private(event) and not self._ingest_private:
            _dry_trace(stats, "skip (private event, not imported)", event)
            _event_log(
                verbose, "skip (private event)", calendar_id, provider_id, google_event_id
            )
            missing = []

        # Convergence guard, applied per day: one (provider, day) gets at most one hold for its whole
        # life. A day whose hold was cancelled out-of-band stays cancelled unless this is a
        # deliberate admin rebuild, so the create -> cancel -> re-create loop can't restart per day.
        if not force_rebuild:
            missing = [
                date
                for date in missing
                if not self._external_value_exists(
                    hold_external_id(google_event_id, date), provider_id
                )
            ]

        effects: list[Effect] = []
        for date in dates:
            hold_id = live_by_date.get(date)
            if hold_id is not None:
                # Only re-issue an update when the Google event's content actually moved; re-saving
                # an unchanged hold is pure write load (the same guard the single-hold path applies).
                if content_changed:
                    effects.append(self._day_hold_update_effect(hold_id, event, date))
                    stats["holds_updated"] = stats["holds_updated"] + 1
            elif date in missing:
                effect = build_hold_effect(
                    event, note_type_id, provider_id, location_id, date
                )
                if effect is None:
                    stats["ignored"] = stats["ignored"] + 1
                    continue
                effects.append(effect)
                stats["holds_created"] = stats["holds_created"] + 1
        for canvas_id in stale:
            effects.append(ScheduleEvent(instance_id=str(canvas_id)).delete())
            stats["holds_removed"] = stats["holds_removed"] + 1

        if not effects:
            stats["ignored"] = stats["ignored"] + 1
            return []

        if not dry_run:
            # Refresh the in-flight marker only when this pass actually issues creates, so an
            # update-only pass can't push the grace window out and stall a later repair.
            if missing:
                PendingHoldCreate.objects.update_or_create(
                    google_event_id=google_event_id,
                    google_calendar_id=calendar_id,
                    defaults={"created_at": arrow.utcnow().datetime},
                )
            InboundEventMapping.objects.update_or_create(
                google_event_id=google_event_id,
                defaults={
                    "google_calendar_id": calendar_id,
                    "last_applied_hash": new_hash,
                },
            )
        _dry_trace(stats, f"would sync all-day event across {len(dates)} day(s)", event)
        _event_log(
            verbose,
            f"reconcile all-day holds ({len(dates)} day(s))",
            calendar_id,
            provider_id,
            google_event_id,
        )
        return effects

    def _create_in_flight(self, pending: PendingHoldCreate | None) -> bool:
        """Is a create for this (calendar, event) still inside the async-apply grace window?

        ``created_at`` missing is treated as in flight: a marker we can't age is safer read as "the
        create may still be applying" than as an invitation to re-issue it.
        """
        if pending is None:
            return False
        created_at = getattr(pending, "created_at", None)
        return created_at is None or (
            (arrow.utcnow() - arrow.get(created_at)).total_seconds()
            < self._PENDING_CREATE_GRACE_SECONDS
        )

    def _within_import_window(self, event: dict) -> bool:
        """Is this event's start within the same ``[now-1mo, now+6mo]`` window a full pull uses?

        Returns ``True`` when the start can't be parsed (let downstream ignore it), so this only ever
        *excludes* an event whose start is legibly outside the window — the guard against a recurring
        series expanding without bound on token-based delta pulls (which send no ``timeMax``).
        """
        window = parse_event_window(event)
        if window is None:
            return True
        start = arrow.get(window[0])
        lower = arrow.utcnow().shift(months=self._FULL_PULL_TIME_MIN_SHIFT_MONTHS)
        upper = arrow.utcnow().shift(months=self._FULL_PULL_TIME_MAX_SHIFT_MONTHS)
        return lower <= start <= upper

    @staticmethod
    def _canvas_id_for_google_event(
        google_event_id: str, provider_id: str | None
    ) -> str | None:
        """Resolve THIS provider's *live* Canvas hold id for a Google event via its external identifier.

        Scoped to ``provider_id`` because a shared multi-attendee event carries the same id on every
        attendee's calendar: an unscoped lookup would return another provider's hold and wrongly route
        this provider's import into the update path. Excludes cancelled appointments, so this answers
        "is there a live hold to UPDATE for this provider?" — not "was one ever created" (that is
        :meth:`_external_hold_exists`).
        """
        canvas_id = (
            AppointmentExternalIdentifier.objects.filter(
                system=GOOGLE_ORIGIN_SYSTEM,
                value=google_event_id,
                appointment__provider__id=provider_id,
            )
            .exclude(appointment__status="cancelled")
            .values_list("appointment__id", flat=True)
            .first()
        )
        return str(canvas_id) if canvas_id else None

    @staticmethod
    def _external_hold_exists(google_event_id: str, provider_id: str | None) -> bool:
        """Has a hold ever been created FOR THIS PROVIDER for this Google event (any status)?

        The convergence backstop, scoped per provider: one (provider, Google event) → at most one
        Canvas hold for its whole life. Scoping is what lets each attendee of a shared event get their
        own hold instead of all-but-the-first being skipped.
        """
        return bool(
            AppointmentExternalIdentifier.objects.filter(
                system=GOOGLE_ORIGIN_SYSTEM,
                value=google_event_id,
                appointment__provider__id=provider_id,
            ).exists()
        )

    @staticmethod
    def _live_holds_for_event(
        google_event_id: str, provider_id: str | None
    ) -> dict[str, str]:
        """Map external-id value -> live Canvas hold id for this (provider, Google event).

        Covers the bare event id (timed events, and all-day holds created before per-day expansion)
        and every ``{event_id}:{date}`` an all-day event expands into. The DB filter is a prefix
        match, which can also catch a *different* event whose id merely starts with this one, so the
        exact separator check in Python is what makes the result precise.
        """
        rows = (
            AppointmentExternalIdentifier.objects.filter(
                system=GOOGLE_ORIGIN_SYSTEM,
                value__startswith=google_event_id,
                appointment__provider__id=provider_id,
            )
            .exclude(appointment__status="cancelled")
            .values_list("value", "appointment__id")
        )
        prefix = f"{google_event_id}:"
        return {
            str(value): str(appointment_id)
            for value, appointment_id in rows
            if str(value) == google_event_id or str(value).startswith(prefix)
        }

    @staticmethod
    def _external_value_exists(value: str, provider_id: str | None) -> bool:
        """Has a hold ever existed FOR THIS PROVIDER under this exact external id (any status)?

        The per-day equivalent of :meth:`_external_hold_exists` — the convergence backstop for one
        day of an expanded all-day event.
        """
        return bool(
            AppointmentExternalIdentifier.objects.filter(
                system=GOOGLE_ORIGIN_SYSTEM,
                value=value,
                appointment__provider__id=provider_id,
            ).exists()
        )

    @staticmethod
    def _day_hold_update_effect(canvas_id: str, event: dict, date: str) -> Effect:
        """Move an existing hold to cover exactly ``date``, one whole day."""
        schedule_event = ScheduleEvent(instance_id=str(canvas_id))
        schedule_event.start_time = arrow.get(date, "YYYY-MM-DD").to("UTC").datetime
        schedule_event.duration_minutes = ALL_DAY_DURATION_MINUTES
        schedule_event.description = hold_title(event)
        return schedule_event.update()

    def _hold_delete_effects(
        self, google_event_id: str, provider_id: str | None
    ) -> list[Effect]:
        """Delete effects for every live hold this provider carries for the Google event.

        A timed event has at most one; an all-day event has one per covered day. A cancellation
        delta carries no start/end, so the days can't be recomputed — going by the stamped external
        ids is the only way to remove the whole set.
        """
        return [
            ScheduleEvent(instance_id=str(canvas_id)).delete()
            for canvas_id in sorted(
                self._live_holds_for_event(google_event_id, provider_id).values()
            )
        ]

    def _hold_update_effect(
        self, google_event_id: str, event: dict, provider_id: str | None
    ) -> Effect | None:
        canvas_id = self._canvas_id_for_google_event(google_event_id, provider_id)
        if not canvas_id:
            return None
        window = parse_event_window(event)
        if window is None:
            return None
        start_time, duration_minutes = window
        schedule_event = ScheduleEvent(instance_id=str(canvas_id))
        schedule_event.start_time = start_time
        schedule_event.duration_minutes = duration_minutes
        # ``hold_title`` masks private/confidential titles on UPDATE too, not just on create —
        # otherwise editing a private Google event would overwrite the "Busy" placeholder with its
        # real (PHI-adjacent) title in Canvas.
        schedule_event.description = hold_title(event)
        return schedule_event.update()
