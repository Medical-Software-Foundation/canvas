"""The day feed, and which incidents a person may correct.

The feed is deliberately not built on total_for, and these tests pin the three
ways it differs. Each difference exists because the feed answers a question the
patient's own record does not, namely what happened on this day and what can I
still do about it.
"""

import arrow

from attendance_policy_tracker.core.attribution import is_correctable
from attendance_policy_tracker.core.config import (
    KIND_LATE_CANCELLATION,
    KIND_LATE_MOVE,
    KIND_NO_SHOW,
)
from attendance_policy_tracker.core.contracts import CLINIC, PATIENT, Incident
from attendance_policy_tracker.core.history import Transition
from attendance_policy_tracker.sweep import union_patient_ids
from tests.test_core import (
    NOW,
    PATIENT_ID,
    PROVIDER_ID,
    FakeSource,
    build_engine,
    history,
)

DAY_START = arrow.get("2026-08-14T00:00:00+00:00").datetime
DAY_END = arrow.get("2026-08-15T00:00:00+00:00").datetime


def incident(kind=KIND_LATE_CANCELLATION, by_patient_portal=False):
    """A bare incident, for the correctability rules."""
    return Incident(
        appointment_id="a1",
        patient_id=PATIENT_ID,
        kind=kind,
        anchor=NOW.datetime,
        occurred_at=NOW.datetime,
        provider_id=PROVIDER_ID,
        by_patient_portal=by_patient_portal,
    )


class TestCorrectability:
    """Only something staff performed is genuinely ambiguous."""

    def test_a_staff_cancellation_is_correctable(self) -> None:
        assert is_correctable(incident()) is True

    def test_a_staff_move_is_correctable(self) -> None:
        assert is_correctable(incident(kind=KIND_LATE_MOVE)) is True

    def test_a_portal_cancellation_is_not_correctable(self) -> None:
        # The portal rule claims it ahead of the label, so a correction here
        # would write a label and move no number.
        assert is_correctable(incident(by_patient_portal=True)) is False

    def test_a_portal_move_is_not_correctable(self) -> None:
        assert is_correctable(incident(kind=KIND_LATE_MOVE, by_patient_portal=True)) is False

    def test_a_missed_visit_is_never_correctable(self) -> None:
        assert is_correctable(incident(kind=KIND_NO_SHOW)) is False


class TestActivityFeed:
    """One day of changes, read by when they happened rather than by visit date."""

    def _cancelled_at(self, moment, labels=None, by_patient=False, appointment_id="a1"):
        """A visit due at the fixed now, cancelled at the given moment.

        Leaving the start at now keeps every cancellation here inside the late
        cutoff, so the detector always fires and each test is only about the day
        boundary or the attribution rather than about lateness.
        """
        return history(
            appointment_id=appointment_id,
            start_offset_days=0,
            transitions=[Transition("CLD", arrow.get(moment).datetime, by_patient=by_patient)],
            labels=labels or [],
        )

    def test_an_incident_inside_the_holding_window_still_appears(self) -> None:
        """The whole point of the feed. total_for hides these, this must not.

        A cancellation made a minute ago is exactly the row somebody opens this
        screen to fix, and the holding window deliberately keeps it off the
        patient's total until it settles.
        """
        just_now = NOW.shift(minutes=-1)
        source = FakeSource([self._cancelled_at(just_now)])
        engine = build_engine(source)

        assert engine.total_for(PATIENT_ID).count == 0
        found = engine.activity_between(DAY_START, DAY_END, [PATIENT_ID])
        assert len(found) == 1
        assert found[0].kind == KIND_LATE_CANCELLATION

    def test_an_incident_already_moved_to_the_clinic_still_appears(self) -> None:
        """Otherwise a correction could never be undone from this screen."""
        source = FakeSource(
            [self._cancelled_at(NOW.shift(hours=-2), labels=["clinic-cancelled"])]
        )
        engine = build_engine(source)

        assert engine.total_for(PATIENT_ID).count == 0
        found = engine.activity_between(DAY_START, DAY_END, [PATIENT_ID])
        assert len(found) == 1
        assert found[0].attribution == CLINIC

    def test_a_change_outside_the_day_is_excluded(self) -> None:
        source = FakeSource([self._cancelled_at(arrow.get("2026-08-13T23:00:00+00:00"))])
        engine = build_engine(source)
        assert engine.activity_between(DAY_START, DAY_END, [PATIENT_ID]) == []

    def test_the_span_is_start_inclusive_and_end_exclusive(self) -> None:
        """So consecutive days neither overlap nor lose anything at midnight."""
        at_end = FakeSource([self._cancelled_at(arrow.get(DAY_END))])
        at_start = FakeSource([self._cancelled_at(arrow.get(DAY_START))])

        assert build_engine(at_end).activity_between(DAY_START, DAY_END, [PATIENT_ID]) == []
        assert len(build_engine(at_start).activity_between(DAY_START, DAY_END, [PATIENT_ID])) == 1

    def test_a_switched_off_kind_does_not_appear(self) -> None:
        source = FakeSource([self._cancelled_at(NOW.shift(hours=-2))])
        engine = build_engine(source, {"counted_kinds": [KIND_NO_SHOW]})
        assert engine.activity_between(DAY_START, DAY_END, [PATIENT_ID]) == []

    def test_rows_come_back_newest_first(self) -> None:
        source = FakeSource(
            [
                self._cancelled_at(NOW.shift(hours=-5), appointment_id="early"),
                self._cancelled_at(NOW.shift(hours=-2), appointment_id="late"),
            ]
        )
        found = build_engine(source).activity_between(DAY_START, DAY_END, [PATIENT_ID])
        assert [item.appointment_id for item in found] == ["late", "early"]

    def test_attribution_matches_what_the_patient_record_would_say(self) -> None:
        """One chain, so the two screens can never disagree about who it counts against."""
        source = FakeSource([self._cancelled_at(NOW.shift(hours=-2), by_patient=True)])
        found = build_engine(source).activity_between(DAY_START, DAY_END, [PATIENT_ID])
        assert found[0].attribution == PATIENT
        assert is_correctable(found[0]) is False

    def test_no_patients_means_no_reads(self) -> None:
        source = FakeSource([])
        assert build_engine(source).activity_between(DAY_START, DAY_END, []) == []
        assert source.calls == 0


class TestMovesJoinTheFeed:
    """A reschedule writes a booked event rather than a cancellation, so
    patients_with_changes_between never sees a move. The route unions in
    patients_with_moves_between beside it, and these pin that the union is
    what actually reaches the feed, exactly as the route builds it.
    """

    def test_a_day_whose_only_activity_is_a_late_move_appears_in_the_feed(self) -> None:
        # Moved two hours before its own start, well inside the day and well
        # inside the default twenty four hour boundary.
        moved = history(
            start_offset_days=0,
            transitions=[Transition("BKD", NOW.shift(hours=-2).datetime)],
            replacement_id="a2",
            moved_offset_hours=2,
        )
        source = FakeSource([moved], moved_ids=[PATIENT_ID])

        patient_ids = union_patient_ids(
            source.patients_with_changes_between(DAY_START, DAY_END, ("CLD", "NSW")),
            source.patients_with_moves_between(DAY_START, DAY_END),
        )
        assert patient_ids == [PATIENT_ID]

        found = build_engine(source).activity_between(DAY_START, DAY_END, patient_ids)
        assert len(found) == 1
        assert found[0].kind == KIND_LATE_MOVE

    def test_a_move_outside_the_boundary_still_produces_no_incident(self) -> None:
        # Discovery finds the patient through the moves method, but a move
        # well outside the boundary earns nothing, so the feed stays empty.
        # Discovery and counting stay separate concerns.
        far_moved = history(
            start_offset_days=0,
            transitions=[Transition("BKD", NOW.shift(hours=-72).datetime)],
            replacement_id="a2",
            moved_offset_hours=72,
        )
        source = FakeSource([far_moved], moved_ids=[PATIENT_ID])

        patient_ids = union_patient_ids(
            source.patients_with_changes_between(DAY_START, DAY_END, ("CLD", "NSW")),
            source.patients_with_moves_between(DAY_START, DAY_END),
        )
        assert patient_ids == [PATIENT_ID]

        found = build_engine(source).activity_between(DAY_START, DAY_END, patient_ids)
        assert found == []


class TestRecordKeepsWhatItDidNotCount:
    """A correction must stay reversible from the screen that made it."""

    def _staff_cancellation(self, labels=None):
        return history(
            start_offset_days=0,
            transitions=[Transition("CLD", NOW.shift(hours=-2).datetime)],
            labels=labels or [],
        )

    def test_an_incident_moved_to_the_clinic_stays_in_the_payload(self) -> None:
        total = build_engine(
            FakeSource([self._staff_cancellation(labels=["clinic-cancelled"])])
        ).total_for(PATIENT_ID)

        assert total.count == 0
        assert total.incidents == []
        # It used to vanish here, which left no control to move it back.
        assert len(total.considered) == 1
        assert total.considered[0].attribution == CLINIC

    def test_the_count_still_reflects_only_what_counts(self) -> None:
        total = build_engine(
            FakeSource(
                [
                    self._staff_cancellation(labels=["clinic-cancelled"]),
                    history(
                        appointment_id="a2",
                        start_offset_days=0,
                        transitions=[Transition("CLD", NOW.shift(hours=-3).datetime)],
                    ),
                ]
            )
        ).total_for(PATIENT_ID)

        assert total.count == 1
        assert len(total.considered) == 2

    def test_the_payload_marks_which_rows_count(self) -> None:
        payload = build_engine(
            FakeSource([self._staff_cancellation(labels=["clinic-cancelled"])])
        ).total_for(PATIENT_ID).as_dict()

        assert payload["count"] == 0
        assert [row["counts"] for row in payload["incidents"]] == [False]
        assert payload["incidents"][0]["correctable"] is True


class TestPendingIsAStateNotAnAbsence:
    """The holding period decides whether an incident counts, not whether it exists."""

    def _just_cancelled(self):
        return history(
            start_offset_days=0,
            transitions=[Transition("CLD", NOW.shift(minutes=-1).datetime)],
        )

    def test_a_fresh_incident_appears_in_the_record(self) -> None:
        """It used to vanish here while showing on the day feed, which is what a
        person saw as cancelling a visit and then not finding it in the chart."""
        total = build_engine(FakeSource([self._just_cancelled()])).total_for(PATIENT_ID)

        assert total.count == 0
        assert len(total.considered) == 1
        assert total.considered[0].pending is True

    def test_a_fresh_incident_is_not_counted(self) -> None:
        total = build_engine(FakeSource([self._just_cancelled()])).total_for(PATIENT_ID)
        payload = total.as_dict()

        assert payload["count"] == 0
        assert payload["incidents"][0]["pending"] is True
        # Not counted, even though attribution put it on the patient.
        assert payload["incidents"][0]["counts"] is False
        assert payload["incidents"][0]["attribution"] == PATIENT

    def test_a_settled_incident_is_not_pending(self) -> None:
        settled = history(
            start_offset_days=0,
            transitions=[Transition("CLD", NOW.shift(hours=-2).datetime)],
        )
        payload = build_engine(FakeSource([settled])).total_for(PATIENT_ID).as_dict()

        assert payload["count"] == 1
        assert payload["incidents"][0]["pending"] is False
        assert payload["incidents"][0]["counts"] is True

    def test_the_day_feed_marks_the_same_state(self) -> None:
        """So one incident reads identically on both surfaces."""
        found = build_engine(FakeSource([self._just_cancelled()])).activity_between(
            DAY_START, DAY_END, [PATIENT_ID]
        )
        assert len(found) == 1
        assert found[0].pending is True


class TestAFutureVisitStillCounts:
    """The cutoff decides whether a cancellation is late, not the calendar."""

    def _cancelled_ahead_of_a_future_visit(self, hours_ahead=14):
        """A visit tomorrow, cancelled now, inside the twenty four hour cutoff."""
        start = NOW.shift(hours=hours_ahead)
        return history(
            start_offset_days=0,
            transitions=[Transition("CLD", NOW.shift(hours=-2).datetime)],
        ), start

    def test_a_late_cancellation_of_an_upcoming_visit_counts(self) -> None:
        """It used to be discarded because its anchor was in the future, so it was
        visible on the day feed and absent from the patient's own record."""
        hist = history(
            start_offset_days=1,
            transitions=[Transition("CLD", NOW.shift(hours=14).datetime)],
        )
        total = build_engine(FakeSource([hist])).total_for(PATIENT_ID)

        assert len(total.considered) == 1
        assert total.considered[0].anchor > NOW.datetime

    def test_an_incident_older_than_the_window_is_still_excluded(self) -> None:
        """Only the far end of the window is bounded."""
        stale = history(
            start_offset_days=-400,
            transitions=[Transition("CLD", NOW.shift(days=-400).datetime)],
        )
        total = build_engine(FakeSource([stale])).total_for(PATIENT_ID)
        assert total.considered == []


class TestWhenAPendingRowStartsCounting:
    """An instant, so a page left open never shows a stale remaining time."""

    def _just_cancelled(self):
        return history(
            start_offset_days=0,
            transitions=[Transition("CLD", NOW.shift(minutes=-1).datetime)],
        )

    def test_a_pending_incident_carries_the_moment_it_starts_counting(self) -> None:
        total = build_engine(FakeSource([self._just_cancelled()])).total_for(PATIENT_ID)
        incident = total.considered[0]

        assert incident.pending is True
        # One minute ago plus the fifteen minute default.
        assert incident.counts_at == NOW.shift(minutes=14).datetime

    def test_a_settled_incident_carries_no_such_moment(self) -> None:
        settled = history(
            start_offset_days=0,
            transitions=[Transition("CLD", NOW.shift(hours=-2).datetime)],
        )
        incident = build_engine(FakeSource([settled])).total_for(PATIENT_ID).considered[0]

        assert incident.pending is False
        assert incident.counts_at is None

    def test_the_moment_follows_the_configured_period(self) -> None:
        total = build_engine(
            FakeSource([self._just_cancelled()]), {"holding_window_minutes": 5}
        ).total_for(PATIENT_ID)
        incident = total.considered[0]

        assert incident.pending is True
        assert incident.counts_at == NOW.shift(minutes=4).datetime

    def test_the_payload_carries_it_as_text(self) -> None:
        payload = build_engine(
            FakeSource([self._just_cancelled()])
        ).total_for(PATIENT_ID).as_dict()

        assert payload["incidents"][0]["pending"] is True
        assert payload["incidents"][0]["counts_at"] is not None
