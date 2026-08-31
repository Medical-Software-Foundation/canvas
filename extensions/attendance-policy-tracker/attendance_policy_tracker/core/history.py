"""What a detector is handed.

These are plain values with no Canvas import anywhere, which is what keeps the
engine and the detectors testable without an instance. The adapter that talks to
Canvas builds them, and it is the only place that knows what a note state change
row looks like.
"""


import datetime


class Transition:
    """One state an appointment moved into."""

    def __init__(
        self,
        state: str,
        occurred_at: datetime.datetime,
        by_patient: bool = False,
        actor_id: str | None = None,
    ) -> None:
        self.state = state
        self.occurred_at = occurred_at
        # True when the person who performed this transition resolved to the
        # patient rather than to a member of staff. Observed on a running
        # instance, the portal path populates this and the staff path does not.
        self.by_patient = by_patient
        self.actor_id = actor_id

    def __repr__(self) -> str:
        return f"Transition(state={self.state}, at={self.occurred_at}, by_patient={self.by_patient})"


class AppointmentHistory:
    """One visit thread, its labels, and every state it moved into.

    Keyed by the note rather than by the appointment, because Canvas keeps the
    state history on the note and a reschedule reuses the original's note rather
    than creating a new one. One note therefore carries the original appointment
    and every replacement, which is exactly one intended visit. Keying by
    appointment instead would let a single moved visit produce two incidents.

    Two starts are carried because the policy measures different things against
    different slots. A late move gave up the slot it was originally booked into,
    while a late cancellation gave up whichever slot it held at the time.
    """

    def __init__(
        self,
        appointment_id: str,
        patient_id: str,
        provider_id: str,
        start_time: datetime.datetime,
        transitions: list[Transition] | None = None,
        labels: list[str] | None = None,
        replacement_id: str | None = None,
        moved_at: datetime.datetime | None = None,
        moved_by_patient: bool = False,
        original_start: datetime.datetime | None = None,
    ) -> None:
        self.appointment_id = appointment_id
        self.patient_id = patient_id
        self.provider_id = provider_id
        # The slot this visit held most recently.
        self.start_time = start_time
        # The slot it was first booked into, which is the same as start_time
        # unless the visit was moved.
        self.original_start = original_start or start_time
        # Kept in the order Canvas wrote them, which is the order they happened.
        self.transitions = list(transitions or [])
        self.labels = list(labels or [])
        # Set when this appointment was moved, pointing at its replacement.
        self.replacement_id = replacement_id
        self.moved_at = moved_at
        self.moved_by_patient = moved_by_patient

    @property
    def was_moved(self) -> bool:
        """True when this appointment was replaced by a later one."""
        return self.replacement_id is not None

    def cancelled_at(
        self, cancelled_states: list[str] | tuple[str, ...]
    ) -> datetime.datetime | None:
        """When this appointment first went to a cancelled state, or None.

        The states are passed in rather than named here, because which strings
        Canvas stores is the adapter's knowledge and this layer is deliberately
        free of it. Only the run rule needs this, since it groups cancellations
        by the moment they happened rather than by the visit they belonged to.
        """
        transition = self.first_transition_into(cancelled_states)
        if transition is None:
            return None
        return transition.occurred_at

    def first_transition_into(
        self, states: list[str] | tuple[str, ...]
    ) -> Transition | None:
        """The earliest transition into any of these states, or None.

        Earliest rather than latest, because the append only history can carry
        the same state more than once and the policy cares about when the visit
        first went that way.
        """
        for transition in self.transitions:
            if transition.state in states:
                return transition
        return None

    def first_unreversed_transition_into(
        self,
        states: list[str] | tuple[str, ...],
        reversing_states: list[str] | tuple[str, ...],
    ) -> Transition | None:
        """The earliest transition into any of these states that still stands, or None.

        A transition stands unless some later transition in the list moved into
        one of the reversing states. The check is positional rather than a search
        for a reversal anywhere in the history, because cancel, then restore, then
        cancel again is a sequence the platform allows, and the second
        cancellation must still be found even though a reversal exists earlier in
        the list. So each candidate transition looks only at what comes after it,
        and the first one with no reversal after it wins.

        This makes no assumption that the history follows the platform's own
        transition table, since the history can carry rows written directly by
        the front end rather than moved through the state machine, and the rule
        has to tolerate whatever order actually arrived.
        """
        for index, candidate in enumerate(self.transitions):
            if candidate.state not in states:
                continue
            reversed_after = any(
                later.state in reversing_states
                for later in self.transitions[index + 1 :]
            )
            if not reversed_after:
                return candidate
        return None

    def __repr__(self) -> str:
        return (
            f"AppointmentHistory(appointment={self.appointment_id}, "
            f"start={self.start_time}, transitions={len(self.transitions)})"
        )
