"""Time arithmetic, injected rather than read from the module.

Every window in the policy is a span, so all the arithmetic lives in one place
and the engine never touches the wall clock directly. A test holds time still by
passing a different clock rather than by patching a module.

Arrow does the work because the plugin sandbox blocks importing timezone
directly, and arrow is already relied on elsewhere in this workspace.
"""

import datetime
from typing import cast

import arrow


class Clock:
    """Real time, in UTC."""

    def now(self) -> datetime.datetime:
        """The current moment."""
        return arrow.utcnow().datetime

    def months_before(self, moment: datetime.datetime, months: int) -> datetime.datetime:
        """The moment that many months earlier, for the counting window."""
        return arrow.get(moment).shift(months=-months).datetime

    def minutes_before(self, moment: datetime.datetime, minutes: int) -> datetime.datetime:
        """The moment that many minutes earlier, for the holding window."""
        return arrow.get(moment).shift(minutes=-minutes).datetime

    def minutes_after(self, moment: datetime.datetime, minutes: int) -> datetime.datetime:
        """The moment that many minutes later, for when an incident starts counting."""
        return arrow.get(moment).shift(minutes=minutes).datetime

    def hours_between(self, earlier: datetime.datetime, later: datetime.datetime) -> float:
        """Hours from the earlier moment to the later one, negative if reversed.

        Used for the lateness gap, where the earlier moment is the cancellation
        and the later one is the appointment start. A cancellation after the
        appointment has already started gives a negative gap, which is still
        inside any positive cutoff and so still counts.
        """
        # Cast because arrow's overloaded __sub__ resolves to its first
        # candidate here rather than the timedelta-returning one, a quirk of
        # its stubs meeting an untyped dateutil, not a real ambiguity at
        # runtime, where two Arrow instances always subtract to a timedelta.
        delta = cast(datetime.timedelta, arrow.get(later) - arrow.get(earlier))
        return delta.total_seconds() / 3600.0

    def minutes_between(self, earlier: datetime.datetime, later: datetime.datetime) -> float:
        """Absolute minutes between two moments, for the run window."""
        # See the cast note in hours_between, same arrow stub quirk.
        delta = cast(datetime.timedelta, arrow.get(later) - arrow.get(earlier))
        return abs(delta.total_seconds()) / 60.0


class FixedClock:
    """A clock held at one moment, for tests and for a reproducible sweep."""

    def __init__(self, moment: datetime.datetime) -> None:
        self._moment = arrow.get(moment).datetime
        self._real = Clock()

    def now(self) -> datetime.datetime:
        """The moment this clock was fixed at."""
        return self._moment

    def months_before(self, moment: datetime.datetime, months: int) -> datetime.datetime:
        """Delegated, since only the current moment is fixed."""
        return self._real.months_before(moment, months)

    def minutes_before(self, moment: datetime.datetime, minutes: int) -> datetime.datetime:
        """Delegated, since only the current moment is fixed."""
        return self._real.minutes_before(moment, minutes)

    def minutes_after(self, moment: datetime.datetime, minutes: int) -> datetime.datetime:
        """Delegated, since only the current moment is fixed."""
        return self._real.minutes_after(moment, minutes)

    def hours_between(self, earlier: datetime.datetime, later: datetime.datetime) -> float:
        """Delegated, since only the current moment is fixed."""
        return self._real.hours_between(earlier, later)

    def minutes_between(self, earlier: datetime.datetime, later: datetime.datetime) -> float:
        """Delegated, since only the current moment is fixed."""
        return self._real.minutes_between(earlier, later)
