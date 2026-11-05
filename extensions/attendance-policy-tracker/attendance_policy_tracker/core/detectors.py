"""Incident detectors, one strategy per counted event type.

A detector is handed one appointment's history and returns an Incident or None.
It never decides who the incident counts against, that belongs to the attribution
chain, and it never looks at anything outside the history it was given.

Every detector reads the appointment's state TRANSITIONS and never its current
status. That distinction is load bearing. Moving a visit leaves the original with
a cancelled status while writing a booking into its history rather than a
cancellation, so a detector reading status would count a moved visit as a
cancellation and then count the move as well.
"""

from typing import Any

from attendance_policy_tracker.core.config import (
    KIND_LATE_CANCELLATION,
    KIND_LATE_MOVE,
    KIND_NO_SHOW,
)
from attendance_policy_tracker.core.contracts import Incident


class NoShowDetector:
    """A visit the patient did not attend.

    Placed first in the chain of detectors, because a no show is unambiguous and
    should never be reinterpreted as something softer by a later detector.
    """

    kind = KIND_NO_SHOW

    def __init__(
        self,
        no_show_states: list[str] | tuple[str, ...],
        reverting_states: list[str] | tuple[str, ...],
    ) -> None:
        self._states = tuple(no_show_states)
        self._reverting = tuple(reverting_states)

    def detect(self, history: Any) -> Incident | None:
        """Yield one incident when the visit was marked as not attended.

        A no show that was later reverted no longer counts, since Restore on the
        note is how a wrong state gets corrected, and a reversal read back as an
        incident would be counting the correction rather than the mistake.
        """
        transition = history.first_unreversed_transition_into(self._states, self._reverting)
        if transition is None:
            return None
        return Incident(
            appointment_id=history.appointment_id,
            patient_id=history.patient_id,
            kind=self.kind,
            anchor=history.start_time,
            occurred_at=transition.occurred_at,
            provider_id=history.provider_id,
            by_patient_portal=False,
            labels=history.labels,
        )


class LateMoveDetector:
    """A visit moved so close to its start that moving it amounted to cancelling.

    Runs ahead of the cancellation detector on purpose. A moved appointment ends
    up with a cancelled status, so letting the cancellation detector see it first
    would attribute the move as a cancellation and lose the distinction the
    policy cares about.

    A visit moved earlier than the boundary produces nothing at all, which is the
    common and blameless case.
    """

    kind = KIND_LATE_MOVE

    def __init__(self, clock: Any, boundary_hours: int) -> None:
        self._clock = clock
        self._boundary_hours = boundary_hours

    def detect(self, history: Any) -> Incident | None:
        """Yield one incident when the visit was moved inside the boundary."""
        if not history.was_moved:
            return None
        moved_at = history.moved_at
        if moved_at is None:
            return None
        # Measured against the slot the visit was originally booked into, since
        # that is the slot the move gave up. Measuring against the slot it moved
        # to would make every move look early.
        gap_hours = self._clock.hours_between(moved_at, history.original_start)
        if gap_hours >= self._boundary_hours:
            return None
        return Incident(
            appointment_id=history.appointment_id,
            patient_id=history.patient_id,
            kind=self.kind,
            anchor=history.original_start,
            occurred_at=moved_at,
            provider_id=history.provider_id,
            by_patient_portal=history.moved_by_patient,
            labels=history.labels,
        )


class LateCancellationDetector:
    """A visit cancelled inside the late cutoff.

    Canvas has no notion of a late cancellation, so lateness is derived here by
    comparing the moment of the cancellation against the start of the appointment
    being cancelled. A cancellation earlier than the cutoff produces nothing.
    """

    kind = KIND_LATE_CANCELLATION

    def __init__(
        self,
        clock: Any,
        cutoff_hours: int,
        cancelled_states: list[str] | tuple[str, ...],
        reverting_states: list[str] | tuple[str, ...],
    ) -> None:
        self._clock = clock
        self._cutoff_hours = cutoff_hours
        self._states = tuple(cancelled_states)
        self._reverting = tuple(reverting_states)

    def detect(self, history: Any) -> Incident | None:
        """Yield one incident when the visit was cancelled inside the cutoff.

        A cancellation that was later reverted no longer counts, since Restore on
        the note is how a wrong state gets corrected, and a reversal read back as
        an incident would be counting the correction rather than the mistake.
        """
        transition = history.first_unreversed_transition_into(self._states, self._reverting)
        if transition is None:
            return None
        gap_hours = self._clock.hours_between(transition.occurred_at, history.start_time)
        if gap_hours >= self._cutoff_hours:
            return None
        return Incident(
            appointment_id=history.appointment_id,
            patient_id=history.patient_id,
            kind=self.kind,
            anchor=history.start_time,
            occurred_at=transition.occurred_at,
            provider_id=history.provider_id,
            by_patient_portal=transition.by_patient,
            labels=history.labels,
        )
