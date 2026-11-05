"""The sweep, the one operation that turns totals into effects.

Shared by the periodic schedule and by the on demand route, so both paths run
exactly the same computation and neither can drift from the other.

It is safe to run at any frequency, and safe to run twice. Nothing is stored, so
each run recomputes from live history, and each task carries an identifier derived
from the patient and the line, so a repeat run cannot create a second task.

since_floor exists for the scheduled path alone. The on demand route never
passes one, and a caller with nothing to offer passes nothing, so this stays
exactly as wide as it has always been unless a caller hands it something
already validated. Validating a stored cursor, deciding whether it can be
trusted at all, is the scheduled handler's job, not this one's.

What this file does own is how far a cursor is allowed to narrow the window.
A trustworthy cursor is still not a safe floor on its own, because an incident
recorded before it goes on maturing out of its holding period afterwards, and
maturing is not a change anybody records. So the window never narrows past the
holding period however recent the cursor is, see HOLDING_FLOOR_GRACE_MINUTES.
"""

import datetime
from typing import Any

from canvas_sdk.effects import Effect

from attendance_policy_tracker.canvas.states import CANCELLED_STATES, NO_SHOW_STATES

# How far back a sweep looks for activity worth recomputing. Wider than the
# schedule interval on purpose, so a missed run is caught up by the next one
# rather than leaving a gap nobody notices.
LOOKBACK_MINUTES = 180

# The extra minutes added to the run window when judging a run of clinic
# cancellations, matching the five minute sweep schedule. A completed run
# stays fully visible for one sweep interval past its own window, so the
# scheduled sweep judges it exactly once. After that it ages out and is
# never revisited, which is what stops the rule from reapplying a label a
# person has deliberately removed. The accepted cost, decided by the owner,
# is that a run falling entirely inside a gap where no sweep ran is never
# tagged, a missed convenience rather than an undone correction.
RUN_JUDGEMENT_GRACE_MINUTES = 5

# The extra minutes added to the holding period when flooring the cursor,
# matching the sweep schedule for the same reason the run judgement carries
# one. A sweep fires on a five minute boundary rather than at the instant an
# incident matures, so a floor of exactly the holding period would sit later
# than the incident by however far into the interval the tick landed, and the
# incident it was meant to catch would fall outside the window again.
HOLDING_FLOOR_GRACE_MINUTES = 5


def union_patient_ids(primary: list[str], secondary: list[str]) -> list[str]:
    """Both discovery paths together, in first seen order with no duplicate.

    A small shared helper because the sweep and the two review routes each
    need exactly this union of a state based discovery and a move based
    discovery, and writing the same three lines three times is the kind of
    duplication a later change is bound to fall out of step with.
    """
    combined = list(primary)
    for patient_id in secondary:
        if patient_id not in combined:
            combined.append(patient_id)
    return combined


class Sweep:
    """Recomputes recently active patients and emits whatever they have earned."""

    def __init__(self, config: Any, engine: Any, actions: Any, source: Any, clock: Any) -> None:
        self._config = config
        self._engine = engine
        self._actions = actions
        self._source = source
        self._clock = clock

    def run(
        self,
        lookback_minutes: int = LOOKBACK_MINUTES,
        since_floor: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        # Returns a mapping rather than a typed result object because both the
        # schedule and the on demand route want different parts of it, the
        # schedule only the effects and the route the counts as well.
        """Tag any clinic runs, then recompute everybody who moved recently.

        The wide discovery window normally reaches back the full lookback, the
        one thing that ever narrows it is since_floor sitting later than that
        floor, a cursor from a healthy cadence naming the last few minutes
        rather than the last three hours. Nothing here is what decides whether
        that cursor can be trusted, a caller passes nothing at all when it
        cannot be, and nothing changes anything about the window below.
        """
        now = self._clock.now()
        lookback_since = self._clock.minutes_before(now, lookback_minutes)
        # A cursor may narrow the window, but never past the holding period. An
        # incident recorded before the cursor is uncounted until its holding
        # period ends, and maturing is not a change anybody records, so no
        # discovery path brings that patient back into range on its own. A
        # cursor trusted without this floor therefore loses the one thing this
        # handler exists to catch, a threshold crossed a few minutes after the
        # incident that crossed it.
        holding_floor = self._clock.minutes_before(
            now, self._config.holding_window_minutes + HOLDING_FLOOR_GRACE_MINUTES
        )
        since = lookback_since
        if since_floor is not None:
            narrowed = min(since_floor, holding_floor)
            if narrowed > since:
                since = narrowed

        effects: list[Effect] = []

        # Tagging comes first, so a run of clinic cancellations is marked before
        # the totals that would otherwise count it against those patients are
        # computed in the same pass. The run judgement runs on its own narrowed
        # span rather than the wide lookback above, see RUN_JUDGEMENT_GRACE_MINUTES.
        run_since = self._clock.minutes_before(
            now, self._config.run_window_minutes + RUN_JUDGEMENT_GRACE_MINUTES
        )
        runs = self._engine.runs_of_clinic_cancellations(run_since)
        effects = effects + self._actions.tag_runs(runs)

        watched = list(CANCELLED_STATES) + list(NO_SHOW_STATES)
        patient_ids = self._source.patients_with_changes_since(since, watched)
        # A second discovery path added beside the existing one rather than a
        # change to it, on purpose, because a reschedule writes a booked event
        # rather than a cancellation and so never shows up in the filter
        # above. Adding to what is already found cannot regress it.
        moved_ids = self._source.patients_with_moves_between(since, now)
        patient_ids = union_patient_ids(patient_ids, moved_ids)

        totals = []
        for patient_id in patient_ids:
            total = self._engine.total_for(patient_id)
            totals.append(total)
            if total.lines_reached:
                effects = effects + self._actions.tasks_for(total)

        return {
            "swept": len(patient_ids),
            "runs_tagged": len(runs),
            "effects": effects,
            "totals": [total.as_dict() for total in totals],
        }
