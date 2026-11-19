"""Which platform changes are worth waking an open surface for.

The two decisions are pure functions on purpose, because the interesting part is
what gets filtered out rather than how an event reaches the handler. Every note
save writes a state and most appointments carry labels that have nothing to do
with attendance, so a filter that is too generous turns every open page into a
recompute loop, and one that is too strict leaves a stale number on screen.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from canvas_sdk.events import Event, EventRequest, EventType

from attendance_policy_tracker.canvas.source import CanvasVisitSource
from attendance_policy_tracker.canvas.states import (
    BOOKED_STATES,
    CANCELLED_STATES,
    NO_SHOW_STATES,
    SCHEDULING_STATES,
)
from attendance_policy_tracker.handlers.live import (
    CHANNEL,
    AttendanceChannel,
    AttendanceNotifier,
    label_matters,
    state_matters,
)
from tests.test_core import NOW

MODULE = "attendance_policy_tracker.handlers.live"


class TestStateChanges:
    """A note state change only matters when it could move a total."""

    def test_a_cancellation_matters(self) -> None:
        assert state_matters({"state": CANCELLED_STATES[0]}) is True

    def test_a_missed_visit_matters(self) -> None:
        assert state_matters({"state": NO_SHOW_STATES[0]}) is True

    def test_a_booking_matters_because_a_reschedule_writes_one(self) -> None:
        assert state_matters({"state": BOOKED_STATES[0]}) is True

    def test_scheduling_does_not_matter(self) -> None:
        assert state_matters({"state": SCHEDULING_STATES[0]}) is False

    def test_an_unrelated_state_does_not_matter(self) -> None:
        assert state_matters({"state": "LKD"}) is False

    def test_a_context_with_no_state_does_not_matter(self) -> None:
        assert state_matters({}) is False


class TestLabelChanges:
    """A label change only matters when it is the tag that decides attribution."""

    def test_the_clinic_tag_matters(self) -> None:
        assert label_matters({"label": "clinic-cancelled"}, "clinic-cancelled") is True

    def test_any_other_label_does_not_matter(self) -> None:
        assert label_matters({"label": "missing-coverage"}, "clinic-cancelled") is False

    def test_a_context_with_no_label_does_not_matter(self) -> None:
        assert label_matters({}, "clinic-cancelled") is False

    def test_an_unreadable_policy_errs_toward_speaking(self) -> None:
        assert label_matters({"label": "missing-coverage"}, None) is True

    def test_an_unreadable_policy_still_needs_a_label(self) -> None:
        assert label_matters({}, None) is False


class TestChannel:
    """The channel name is part of the contract with the page."""

    def test_the_channel_is_a_legal_broadcast_channel(self) -> None:
        # The platform rejects anything outside word characters and hyphens, and
        # the page hardcodes this name in its socket URL.
        assert CHANNEL == "attendance"
        assert CHANNEL.replace("-", "").replace("_", "").isalnum()


class FakeRelated:
    """A stand in for a related row, carrying only the id the adapter reads."""

    def __init__(self, id: str) -> None:
        self.id = id


class FakeAppointment:
    """A stand in for a Canvas Appointment row, carrying only what the adapter reads.

    dbid stands for the primary key, which is what a self referencing foreign
    key actually targets, while id is the separate plugin facing identifier the
    adapter names a visit by. appointment_rescheduled_from_id defaults to None,
    so a fake appointment with no reschedule history needs nothing extra.
    """

    def __init__(
        self,
        id,
        dbid,
        start_time,
        provider=None,
        patient=None,
        appointment_rescheduled_from_id=None,
    ) -> None:
        self.id = id
        self.dbid = dbid
        self.start_time = start_time
        self.provider = provider
        self.patient = patient
        self.appointment_rescheduled_from_id = appointment_rescheduled_from_id


def _channel_event(channel_name: str = CHANNEL, headers: dict[str, str] | None = None):
    """A SIMPLE_API_WEBSOCKET_AUTHENTICATE event, the shape WebSocket(event) reads."""
    request = EventRequest(
        type=EventType.SIMPLE_API_WEBSOCKET_AUTHENTICATE,
        target=None,
        context=json.dumps({"channel_name": channel_name, "headers": headers or {}}),
    )
    return Event(request)


def _handler_event(event_type, context: dict):
    """A plain platform event, the shape AttendanceNotifier.compute() reads."""
    request = EventRequest(type=event_type, target=None, context=json.dumps(context))
    return Event(request)


class TestAttendanceChannelGating:
    """Who may open the shared broadcast channel."""

    def test_a_request_for_a_different_channel_is_never_accepted(self) -> None:
        handler = AttendanceChannel(_channel_event(channel_name="some-other-plugin"))
        assert handler.accept_event() is False

    def test_a_request_for_this_channel_is_accepted(self) -> None:
        handler = AttendanceChannel(_channel_event())
        assert handler.accept_event() is True

    def test_a_staff_session_is_authenticated(self) -> None:
        handler = AttendanceChannel(
            _channel_event(
                headers={
                    "canvas-logged-in-user-id": "a" * 32,
                    "canvas-logged-in-user-type": "Staff",
                }
            )
        )
        assert handler.authenticate() is True

    def test_a_patient_session_is_refused(self) -> None:
        # The review surface is staff facing, so a patient portal session must
        # never be able to watch it update.
        handler = AttendanceChannel(
            _channel_event(
                headers={
                    "canvas-logged-in-user-id": "a" * 32,
                    "canvas-logged-in-user-type": "Patient",
                }
            )
        )
        assert handler.authenticate() is False

    def test_no_session_headers_at_all_is_refused(self) -> None:
        # The platform simply omits the header rather than sending an empty
        # one, so websocket.logged_in_user is None, not a mapping to read.
        handler = AttendanceChannel(_channel_event(headers={}))
        assert handler.authenticate() is False


class TestAttendanceNotifierSpeaksOnlyWhenSomethingCouldHaveMoved:
    def test_a_matching_state_change_broadcasts(self) -> None:
        handler = AttendanceNotifier(
            _handler_event(
                EventType.NOTE_STATE_CHANGE_EVENT_CREATED, {"state": CANCELLED_STATES[0]}
            )
        )
        assert len(handler.compute()) == 1

    def test_a_non_matching_state_change_stays_silent(self) -> None:
        handler = AttendanceNotifier(
            _handler_event(EventType.NOTE_STATE_CHANGE_EVENT_CREATED, {"state": "LKD"})
        )
        assert handler.compute() == []

    def test_the_matching_clinic_tag_label_broadcasts(self) -> None:
        handler = AttendanceNotifier(
            _handler_event(EventType.APPOINTMENT_LABEL_ADDED, {"label": "clinic-cancelled"})
        )
        config = SimpleNamespace(clinic_tag="clinic-cancelled")
        with patch(f"{MODULE}.build", return_value={"config": config}):
            effects = handler.compute()
        assert len(effects) == 1

    def test_an_unrelated_label_stays_silent(self) -> None:
        handler = AttendanceNotifier(
            _handler_event(EventType.APPOINTMENT_LABEL_ADDED, {"label": "unrelated"})
        )
        config = SimpleNamespace(clinic_tag="clinic-cancelled")
        with patch(f"{MODULE}.build", return_value={"config": config}):
            effects = handler.compute()
        assert effects == []

    def test_a_policy_read_that_fails_still_broadcasts_rather_than_going_stale(self) -> None:
        handler = AttendanceNotifier(
            _handler_event(EventType.APPOINTMENT_LABEL_ADDED, {"label": "anything"})
        )
        with patch(f"{MODULE}.build", side_effect=RuntimeError("store unreadable")):
            effects = handler.compute()
        assert len(effects) == 1

    def test_the_clinic_tag_lookup_is_never_run_for_a_state_event(self) -> None:
        # Reading policy costs a query, and note traffic is frequent enough
        # that it must never pay for a lookup it cannot use.
        handler = AttendanceNotifier(
            _handler_event(
                EventType.NOTE_STATE_CHANGE_EVENT_CREATED, {"state": CANCELLED_STATES[0]}
            )
        )
        with patch(f"{MODULE}.build") as build_fn:
            handler.compute()
        build_fn.assert_not_called()


class TestNoteOrientation:
    """Which row is the original and which is current, read off the reschedule link.

    Built from the private orientation entry point directly, because these cases
    are about the ordering rule itself rather than about anything a full instance
    would add. Start time cannot be trusted once a visit was moved to an earlier
    slot, so the chain has to be followed instead, and these pin that it is.
    """

    def _history_for(self, in_note):
        return CanvasVisitSource()._history_for_note(in_note, [], [])

    def test_a_visit_moved_later_behaves_exactly_as_today(self) -> None:
        # The regression guard. No reschedule link at all would also reach this
        # answer through the fallback, so the link is set to prove the chain
        # agrees with the clock rather than merely not disagreeing with it.
        original = FakeAppointment("a1", 1, NOW.shift(days=-3).datetime)
        current = FakeAppointment(
            "a2", 2, NOW.shift(days=1).datetime, appointment_rescheduled_from_id=1
        )
        history = self._history_for([original, current])
        assert history.original_start == original.start_time
        assert history.start_time == current.start_time
        assert history.appointment_id == "a2"

    def test_a_visit_moved_earlier_reports_the_abandoned_slot_as_given_up(self) -> None:
        abandoned = FakeAppointment(
            "a1", 1, NOW.shift(days=5).datetime, provider=FakeRelated("p1")
        )
        moved_to = FakeAppointment(
            "a2",
            2,
            NOW.shift(days=1).datetime,
            provider=FakeRelated("p2"),
            appointment_rescheduled_from_id=1,
        )
        history = self._history_for([abandoned, moved_to])
        # The slot given up is the abandoned row's, later than the one moved to.
        assert history.original_start == abandoned.start_time
        assert history.start_time == moved_to.start_time
        assert history.appointment_id == "a2"
        assert history.provider_id == "p2"

    def test_a_visit_moved_twice_follows_the_chain_rather_than_the_clock(self) -> None:
        # c sits between a and b on the clock, so sorting by start time would
        # wrongly call b current. Only the chain gets this right.
        a = FakeAppointment("a", 1, NOW.shift(days=-10).datetime)
        b = FakeAppointment("b", 2, NOW.shift(days=10).datetime, appointment_rescheduled_from_id=1)
        c = FakeAppointment("c", 3, NOW.datetime, appointment_rescheduled_from_id=2)
        history = self._history_for([a, b, c])
        assert history.appointment_id == "c"
        assert history.original_start == a.start_time
        assert history.start_time == c.start_time

    def test_a_single_appointment_thread_is_unchanged(self) -> None:
        only = FakeAppointment("a1", 1, NOW.datetime)
        history = self._history_for([only])
        assert history.original_start == only.start_time
        assert history.start_time == only.start_time
        assert history.appointment_id == "a1"
