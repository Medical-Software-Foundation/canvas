"""The counting engine, the part worth reusing.

It depends on three contracts and never on Canvas. A source hands it appointment
histories, detectors turn a history into at most one incident, and an attribution
chain decides who each incident counts against. Swapping any of those is a
composition root change, not an engine change.

Nothing is stored. A total is rebuilt from history every time it is asked for,
which is what makes a correction free. Removing a tag does not need a repair pass
because there is no stored number to repair.
"""

import datetime
from typing import Any, cast

from attendance_policy_tracker.core.attribution import is_correctable
from attendance_policy_tracker.core.contracts import Incident

WARNING = "warning"
DISCHARGE_REVIEW = "discharge_review"


class Total:
    """What one patient's history adds up to right now."""

    def __init__(
        self,
        patient_id: str,
        count: int,
        incidents: list[Incident],
        lines_reached: list[str],
        considered: list[Incident] | None = None,
    ) -> None:
        self.patient_id = patient_id
        self.count = count
        self.incidents = list(incidents)
        # Every incident the window and the holding period let through, including
        # the ones attribution moved off the patient. The count is still the
        # counted ones, this is so a surface can show what it decided not to
        # count rather than letting a row vanish when somebody corrects it.
        self.considered = list(incidents if considered is None else considered)
        # Which lines this total reaches or passes, in ascending order.
        self.lines_reached = list(lines_reached)

    def reaches(self, line: str) -> bool:
        """True when this total reaches or passes the named line."""
        return line in self.lines_reached

    def as_dict(self) -> dict[str, Any]:
        """A shape a page can render."""
        return {
            "patient_id": f"{self.patient_id}",
            "count": self.count,
            "lines_reached": list(self.lines_reached),
            "incidents": [
                {
                    "appointment_id": f"{incident.appointment_id}",
                    "kind": incident.kind,
                    "anchor": f"{incident.anchor}",
                    "occurred_at": f"{incident.occurred_at}",
                    "attribution": incident.attribution,
                    "counts": incident.counts_against_patient() and not incident.pending,
                    # Recorded but not counted yet, and it will begin counting on
                    # its own once the holding period passes.
                    "pending": incident.pending,
                    "counts_at": f"{incident.counts_at}" if incident.counts_at else None,
                    # Who performed the change, so the record can say what happened
                    # and by whom in the same words the day feed uses.
                    "by_patient_portal": incident.by_patient_portal,
                    # Whether a person may change who this counts against. The
                    # patient's own portal action and a missed visit are settled
                    # facts, so only something staff performed is correctable.
                    "correctable": is_correctable(incident),
                }
                for incident in self.considered
            ],
        }


class AttendanceEngine:
    """Turns a patient's appointment history into a total and the lines it reaches."""

    def __init__(
        self,
        config: Any,
        source: Any,
        detectors: list[Any],
        chain: Any,
        clock: Any,
        cancelled_states: list[str] | tuple[str, ...] = (),
    ) -> None:
        self._config = config
        self._source = source
        self._detectors = list(detectors)
        self._chain = chain
        # Injected rather than read from the module, so a test can hold time
        # still and the engine has no hidden dependency on the wall clock.
        self._clock = clock
        # Which stored state strings mean cancelled. Only the run rule needs
        # them, and they are passed in so this layer stays free of Canvas
        # vocabulary.
        self._cancelled_states = tuple(cancelled_states)

    def total_for(self, patient_id: str) -> Total:
        """Recompute this patient's total from their own history."""
        now = self._clock.now()
        window_start = self._clock.months_before(now, self._config.counting_window_months)
        visible_before = self._clock.minutes_before(now, self._config.holding_window_minutes)
        install_floor = self._config.install_floor

        # The same later of the two moments the loop below filters on, computed
        # once up front so it can be pushed into the read itself rather than
        # only discovered after everything was already fetched. A source that
        # offers the narrower method reads only what could still matter, one
        # that does not still gets a correct total from the unabridged read,
        # because the filter below is what actually decides what counts either
        # way, this is only ever an optimisation on top of it.
        since = install_floor if (install_floor is not None and install_floor > window_start) else window_start
        narrowed = getattr(self._source, "histories_since", None)
        histories = narrowed(patient_id, since) if narrowed is not None else self._source.histories_for(patient_id)

        considered = []
        counted = []
        for history in histories:
            incident = self._incident_from(history)
            if incident is None:
                continue
            if not self._config.counts(incident.kind):
                continue
            # Anchored to the appointment start, so a cancellation of a visit
            # that was already outside the window does not drag it back in. Only
            # the far end is bounded. A visit still in the future is exactly the
            # case a late cancellation covers, and the cutoff has already decided
            # that, so bounding this end hid those until the visit time passed.
            if incident.anchor < window_start:
                continue
            # The install floor, the moment this plugin was stamped into
            # existence. Clinical history predating it is not counted against
            # anybody, because nobody was being told the policy was in force
            # yet. A missing floor counts everything, which is today's
            # behaviour and the safe fallback before the install handler has
            # had its one chance to write it.
            if install_floor is not None and incident.anchor < install_floor:
                continue
            # The holding window decides whether an incident counts, not whether
            # it exists. Nothing pending is stored, so nothing is lost on a
            # reinstall, and a tag applied inside the window still costs nothing.
            self._mark_settling(incident, visible_before)
            self._chain.apply(incident)
            # Kept whoever it ended up against and whether it has settled. A
            # correction moving an incident to the clinic, or a cancellation made
            # a minute ago, both used to drop out of the record entirely.
            considered.append(incident)
            if incident.pending:
                continue
            if incident.counts_against_patient():
                counted.append(incident)

        count = len(counted)
        return Total(patient_id, count, counted, self._lines_reached(count), considered)

    def activity_between(
        self, start: datetime.datetime, end: datetime.datetime, patient_ids: list[str]
    ) -> list[Incident]:
        """Every incident whose change was recorded inside the span, attributed.

        Deliberately not built on total_for, which would be the obvious reuse and
        would be wrong three times over. That method skips anything younger than
        the holding window, which is exactly the rows a person opens this feed to
        act on. It keeps only what counts against the patient, so a cancellation
        already moved to the clinic would vanish and could never be moved back.
        And it filters on the appointment start, whereas this reads by the moment
        the change happened, which is the axis a day is measured on.

        What it does keep is the kind filter, so a practice that stopped counting
        moved visits does not see them here either, and the attribution chain, so
        who an incident counts against can never differ between this feed and the
        patient's own record.
        """
        visible_before = self._clock.minutes_before(
            self._clock.now(), self._config.holding_window_minutes
        )
        found: list[Incident] = []
        for patient_id in patient_ids:
            for history in self._source.histories_for(patient_id):
                incident = self._incident_from(history)
                if incident is None:
                    continue
                if not self._config.counts(incident.kind):
                    continue
                if incident.occurred_at < start or incident.occurred_at >= end:
                    continue
                self._mark_settling(incident, visible_before)
                self._chain.apply(incident)
                found.append(incident)
        # Most recent first, because a feed is read from the top and the change
        # somebody just made is the one they came to look at.
        return sorted(found, key=lambda item: item.occurred_at, reverse=True)

    def _mark_settling(self, incident: Incident, visible_before: datetime.datetime) -> None:
        """Note whether this incident has settled, and when it will."""
        incident.pending = incident.occurred_at > visible_before
        incident.counts_at = (
            self._clock.minutes_after(
                incident.occurred_at, self._config.holding_window_minutes
            )
            if incident.pending
            else None
        )

    def _incident_from(self, history: Any) -> Incident | None:
        """At most one incident per appointment, from the first detector to claim it.

        One appointment contributing one incident is a rule rather than an
        accident. The state history is append only and a single visit can carry
        several transitions, so taking the first detector that fires is what
        stops one visit being counted twice.
        """
        for detector in self._detectors:
            incident = detector.detect(history)
            if incident is not None:
                # Detectors are duck typed collaborators, so the engine only
                # knows detect() returns something, not that it is an Incident.
                return cast(Incident, incident)
        return None

    def _lines_reached(self, count: int) -> list[str]:
        """Which lines a count reaches, ascending.

        Both lines are reported when a count clears both in one evaluation. The
        alternative, reporting only the higher one, would silently skip the
        warning for a patient who arrived at the review line in one step.
        """
        reached: list[str] = []
        if count >= self._config.warning_line:
            reached.append(WARNING)
        if count >= self._config.discharge_review_line:
            reached.append(DISCHARGE_REVIEW)
        return reached

    def runs_of_clinic_cancellations(self, since: datetime.datetime) -> list[dict[str, Any]]:
        """Groups of cancellations against one provider that look like the clinic's.

        A run is the plugin's own evidence that a batch of cancellations was the
        clinic's doing rather than a coincidence of patients. It reads across
        patients, so it takes its own path rather than going through total_for.
        """
        window = self._config.run_window_minutes
        needed = self._config.run_count
        by_provider: dict[str, list[Any]] = {}
        for history in self._source.recent_cancellations(since):
            key = f"{history.provider_id}"
            existing = by_provider.get(key) or []
            # Rebuilt rather than appended in place, because augmented
            # subscript assignment is not available in the plugin sandbox.
            by_provider[key] = existing + [history]

        runs: list[dict[str, Any]] = []
        for provider_id, histories in by_provider.items():
            ordered = sorted(
                histories, key=lambda item: item.cancelled_at(self._cancelled_states)
            )
            for index in range(len(ordered)):
                head = ordered[index]
                head_at = head.cancelled_at(self._cancelled_states)
                group = [
                    candidate
                    for candidate in ordered[index:]
                    if self._clock.minutes_between(
                        head_at, candidate.cancelled_at(self._cancelled_states)
                    )
                    <= window
                ]
                if len(group) >= needed:
                    runs.append({"provider_id": provider_id, "appointments": group})
                    break
        return runs
