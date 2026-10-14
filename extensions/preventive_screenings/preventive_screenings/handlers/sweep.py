"""Rewrite the cards that time changed, on a schedule.

``handlers.event_handlers`` covers everything the chart can tell us. This covers
what it cannot: a patient turning 45, an interval running out, a due screening
tipping overdue. No event fires for any of those, and because protocol cards are
stored state, a card that nobody rewrites is a card that stays wrong.

**Why this is not a nightly sweep of the whole panel.** Two reasons, and the
second is the hard one:

1. Every time-driven change has a date that is knowable when the cards are
   written, so a patient can be revisited on that date rather than examined
   nightly on the chance something moved. ``next_change_date`` works it out and
   ``ScreeningReview`` stores it.
2. A run returns its effects in a single list. On a large panel a full sweep
   would be hundreds of thousands of cards in one list, which does not run at
   all. Bounded batches are not an optimisation here; they are the only thing
   that works, at any panel size.

**Only carded screenings are swept.** A protocol card is opt-in per screening
and off by default, so a practice that cards nothing runs none of this: the
early return below costs two keyed reads a minute and writes nothing. The
chart-side record app shows every tracked screening regardless, and computes it
live, so nothing is hidden by a card being off - only the stored copy is.

Each run takes at most ``batch_size(...)`` patients, in priority order:

* patients whose predicted date has arrived, oldest first;
* then patients with no row yet, which is the backfill after a fresh install.

The knobs are ``SCHEDULE`` and ``batch_size`` together: their product is how
fast the panel can be worked through, and a fresh install on a large instance is
paced by it until every patient has a row.

**That product is a correctness constraint, not a performance preference.**
``sweep_store.MAX_REVIEW_GAP_DAYS`` promises no patient goes more than 90 days
without review, and ``sweep_store.retire`` drops a retired screening's id after
the same 90 days on the assumption that every patient has been reached by then.
Both are only true while ``batch × runs per day × 90`` exceeds the panel size.
Below that, patients silently miss their review and retracted cards strand on
charts forever. Changing either knob means checking it against that.
"""

from datetime import UTC, date, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from preventive_screenings.services.config_store import carded_screenings, load_config
from preventive_screenings.services.review import review_patients

# Imported by name, never as `from ...services import sweep_store` followed by
# `sweep_store.load_state()`. The sandbox's _safe_getattr rejects attribute
# access on an imported module object, and it does so at RUN time - the handler
# loads cleanly and `canvas validate` passes, then the first real invocation
# raises. tests/test_sandbox_safety.py keeps this from coming back.
from preventive_screenings.services.sweep_store import (
    clamp,
    config_stamp,
    fingerprint,
    invalidate_all,
    load_reviews,
    load_state,
    patients_due,
    patients_unseen,
    record_all,
    retire,
    save_state,
)

# How many bytes of effects one run may return. A run's cards go back in a
# single list, which becomes one `EventResponse` protobuf message (`repeated
# Effect effects`), so two separate ceilings apply.
#
# Measured on a Canvas instance 2026-09-20 by returning padded cards at 0.5, 1,
# 2, 4 and 5 MiB:
#
#   * **The message.** gRPC's default maximum length is 4 MiB. 4.2 MiB was
#     accepted without error, so the stock default was not in force there - but
#     a plugin Canvas ships to every practice cannot assume that of every
#     instance.
#   * **The runner's memory watchdog, which binds first.** At 5 MiB the runner
#     logged `Plugin RSS: Excessive memory growth of 10.00MB ... (CronTask
#     .compute)`; at 4 MiB it did not. Effects cost roughly twice their payload
#     in resident memory, and the threshold is somewhere at or below 8.96 MB
#     (seen on another plugin at load).
#
# Half the gRPC default sits under both: ~4 MB of RSS growth, no warning.
EFFECT_BUDGET_BYTES = 2 * 1024 * 1024

# The largest card the configuration can produce - not the largest one the
# shipped screenings happen to produce.
#
# Those are very different numbers, and using the second is what makes this
# constant dangerous. A realistic overdue card carrying an order recommendation
# is 648 bytes, and the six shipped screenings peak at 856. But a practice
# writes its own text, and the worst card `config_store`'s caps permit - a
# maximum-length name, MAX_SIGNALS_PER_SCREENING labels at full length in the
# narrative, and full-length order text - measures 2,606 bytes, four times
# that. Sizing a run against 1024 meant a config that is entirely legal
# overruns EFFECT_BUDGET_BYTES, and the overrun is silent: the effects list is
# dropped whole *after* `record()` has marked those patients reviewed.
#
# So this is derived from the caps, with headroom, and
# `test_the_worst_card_the_config_allows_fits_the_budget` fails if a cap moves
# out from under it. Sizing against the worst case rather than the typical one
# costs only smaller runs - the panel ceiling stays in the millions either way -
# where being wrong the other way loses cards without saying so.
WORST_CARD_BYTES = 3072

# Even with room left in the message, a run stays a bounded unit of work. The
# database cost is flat in the batch size - services/completion reads a whole
# batch in one query per source - but a run that takes minutes is one that
# overlaps the next tick.
BATCH_CEILING = 400


def batch_size(screening_count: int) -> int:
    """How many patients one run may take, given how many screenings are on.

    Not a constant, because what a patient costs *is* the number of enabled
    screenings: every enabled screening emits a card for every patient, so a
    practice tracking the 40-screening maximum fits a sixth as many patients in
    a run as one tracking six.

    A fixed batch is therefore only ever right for the screening count it was
    chosen against, and it fails in the worst way - the message exceeds the
    limit and the run's cards are dropped whole, with the sweep having already
    recorded those patients as reviewed.
    """
    per_patient = WORST_CARD_BYTES * max(screening_count, 1)
    return max(1, min(BATCH_CEILING, EFFECT_BUDGET_BYTES // per_patient))


# Every minute. Frequency is the safer of the two throughput levers: a shorter
# interval costs only steady database load, where a bigger batch pushes against
# the message ceiling above. The database cost per run no longer grows with the
# batch, and an idle run is a handful of queries, so this is cheap.
#
# It is also the *only* lever on how fast an edited rule reaches a chart. The
# sweep invalidates and reviews in the same tick - `invalidate_all` sets
# next_review to today and `patients_due` picks those rows up a few lines later
# - so nothing rewrites a card until a tick happens, and the interval is the
# whole of the discovery latency. Dropping it from five minutes to one is what
# takes an admin's rule change from "up to five minutes before anything moves"
# to "up to one".
#
# (An earlier note in CLAUDE.md suggested calling `invalidate_all` from
# `api/routes.put_config` to fix this. It would not: setting next_review early
# changes nothing while the sweep is still the only thing that writes cards.)
#
# Time-driven changes themselves are never urgent to the minute - a screening
# that came due overnight is no less due at nine - but the drain rate has to
# satisfy the 90-day promise in sweep_store.MAX_REVIEW_GAP_DAYS at the panel
# sizes this is meant for. At 1,440 runs a day that is ~490,000 patients a day
# at six screenings and ~73,000 at the 40-screening maximum, five times the
# headroom the old interval gave.
SWEEP_SCHEDULE = "* * * * *"


class PreventiveScreeningSweep(CronTask):
    """Rewrite the cards whose answer changed because the date changed."""

    SCHEDULE = SWEEP_SCHEDULE

    def execute(self) -> list[Effect]:
        """Review one bounded batch of patients and write only what changed."""
        doc = load_config()
        # Only the screenings that are actually carded. A practice that tracks
        # twelve screenings and cards two pays for two: the chart reads below
        # are driven by this list, so the rest cost nothing here and are
        # computed live by the record app instead.
        screenings = carded_screenings(doc)

        today = datetime.now(UTC).date()
        # Read before the early return, not after, because "nothing to card"
        # is not the same as "nothing to do". Switching the last card off has
        # to retract it from every chart it reached, and the only record that
        # it was ever carded is in this state row. Returning on an empty
        # screening list - which is what this did until cards became opt-in -
        # would strand those cards permanently.
        state = load_state()
        stamp = config_stamp(doc)
        carded_ids = [screening["id"] for screening in screenings]

        if stamp != state["stamp"]:
            # The rules themselves changed, so every stored prediction is stale
            # and there is no event that says so. Mark the panel and let the
            # following runs drain it in batches. Any screening that stopped
            # being carded is remembered here, because its card has to be
            # overwritten patient by patient - nothing deletes a protocol card.
            state = retire(state, carded_ids, today)
            save_state(
                state["cursor"], stamp, state["tracked"], state["retired"]
            )
            state["stamp"] = stamp
            # Requeue the panel only when a review could actually produce
            # something. With nothing carded and nothing to retract, every
            # patient would be walked through a review that returns no cards,
            # paying the bookkeeping write for each - the whole panel drained
            # to write nothing. An edit to a screening the practice does not
            # card is exactly that case, and it is the common one now.
            if carded_ids or state["retired"]:
                marked = invalidate_all(today)
                log.info(
                    f"preventive_screenings sweep: rules changed, {marked} patients "
                    f"requeued, retracting {len(state['retired'])} screening(s)"
                )

        cursor = state["cursor"]
        retired = list(state["retired"])

        if not screenings and not retired:
            # No cards to write and none to take back. Silent on purpose: this
            # is the steady state of an install that cards nothing, and a line
            # a minute saying so would bury the heartbeat below, which exists
            # to distinguish "nothing due" from "stopped running".
            return []
        # Sized against how many screenings are on, plus the ones being retracted
        # this cycle - a retraction is a card too, and forgetting that would
        # overrun the message on exactly the run that was clearing up.
        batch = batch_size(len(screenings) + len(retired))
        keys = patients_due(today, batch)

        # Only reach for unseen patients once the due queue is short, so a
        # backfill never starves patients whose cards are actually wrong today.
        if len(keys) < batch:
            unseen = patients_unseen(cursor, batch - len(keys))
            if unseen:
                keys += [key for key, _dbid in unseen]
                cursor = max(dbid for _key, dbid in unseen)
                save_state(cursor, stamp, state["tracked"], state["retired"])

        if not keys:
            # Say so. A sweep with nothing to do is the *normal* steady state
            # once the panel is drained, and staying silent made it
            # indistinguishable from a sweep that had stopped running - which
            # cost a wrong diagnosis on 2026-09-20, and left a schedule change
            # unverifiable the same afternoon. One line every SCHEDULE is
            # cheaper than that ambiguity.
            log.info(f"preventive_screenings sweep: nothing due, batch {batch}")
            return []

        known = load_reviews(keys)
        # One read of the batch's charts, not one per patient. See
        # services.completion: reviewing patients one at a time cost this run a
        # full set of source queries each, which is what capped BATCH.
        reviews = review_patients(keys, screenings, today, retired)

        effects: list[Effect] = []
        entries: list[tuple[str, date, str]] = []
        rewritten = 0
        for patient_key in keys:
            review = reviews[patient_key]
            mark = fingerprint(review.effects)
            row = known.get(patient_key)
            if review.effects and (row.fingerprint if row else None) != mark:
                effects += review.effects
                rewritten += 1
            entries.append((patient_key, clamp(review.next_review, today), mark))

        # One write for the batch. Per patient this was a SELECT plus an
        # INSERT or UPDATE - 226 queries for a default batch, beside the <=6
        # the chart reads for the same run cost.
        record_all(entries, known, today)

        log.info(
            f"preventive_screenings sweep: reviewed {len(keys)}, rewrote {rewritten}, "
            f"{len(effects)} cards, cursor {cursor}"
        )
        return effects
