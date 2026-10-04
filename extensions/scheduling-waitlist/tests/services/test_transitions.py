"""Status changes: which are allowed, and what gets recorded."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from scheduling_waitlist.constants import (
    STATUS_EXPIRED,
    STATUS_OFFERED,
    STATUS_REMOVED,
    STATUS_SCHEDULED,
    STATUS_WAITING,
)
from scheduling_waitlist.services.transitions import (
    TransitionError,
    apply_transition,
    is_allowed,
    requires_reason,
    validate_transition,
)

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def entry(status=STATUS_WAITING, **attrs):
    record = MagicMock()
    record.status = status
    record.scheduled_appointment_id = attrs.pop("scheduled_appointment_id", None)
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


class TestIsAllowed:
    def test_waiting_may_be_offered(self):
        assert is_allowed(STATUS_WAITING, STATUS_OFFERED) is True

    def test_offered_may_return_to_waiting_when_outreach_fails(self):
        assert is_allowed(STATUS_OFFERED, STATUS_WAITING) is True

    def test_waiting_may_be_scheduled(self):
        assert is_allowed(STATUS_WAITING, STATUS_SCHEDULED) is True

    def test_a_scheduled_entry_may_be_put_back_on_the_list(self):
        # This is the re-arm path used when the booking is later cancelled.
        assert is_allowed(STATUS_SCHEDULED, STATUS_WAITING) is True

    def test_every_closed_status_can_be_reinstated(self):
        for closed in (STATUS_SCHEDULED, STATUS_REMOVED, STATUS_EXPIRED):
            assert is_allowed(closed, STATUS_WAITING) is True, closed

    def test_a_scheduled_entry_does_not_jump_straight_to_expired(self):
        assert is_allowed(STATUS_SCHEDULED, STATUS_EXPIRED) is False

    def test_staying_put_is_not_a_transition(self):
        assert is_allowed(STATUS_WAITING, STATUS_WAITING) is False

    def test_an_invented_status_is_refused(self):
        assert is_allowed(STATUS_WAITING, "parked") is False

    def test_an_unknown_starting_status_permits_nothing(self):
        assert is_allowed("mystery", STATUS_WAITING) is False


class TestRequiresReason:
    def test_leaving_an_automatic_status_needs_an_explanation(self):
        assert requires_reason(STATUS_SCHEDULED) is True
        assert requires_reason(STATUS_EXPIRED) is True

    def test_ordinary_statuses_do_not(self):
        assert requires_reason(STATUS_WAITING) is False
        assert requires_reason(STATUS_OFFERED) is False


class TestValidateTransition:
    def test_an_allowed_change_returns_the_reason_to_store(self):
        assert validate_transition(STATUS_WAITING, STATUS_OFFERED, "  called  ") == "called"

    def test_an_overlong_reason_is_truncated(self):
        stored = validate_transition(STATUS_WAITING, STATUS_OFFERED, "x" * 500)

        assert len(stored) == 200

    def test_an_unknown_target_is_refused(self):
        with pytest.raises(TransitionError, match="not a status"):
            validate_transition(STATUS_WAITING, "parked", "")

    def test_repeating_the_current_status_is_refused(self):
        with pytest.raises(TransitionError, match="already"):
            validate_transition(STATUS_WAITING, STATUS_WAITING, "")

    def test_a_disallowed_change_is_refused(self):
        with pytest.raises(TransitionError, match="cannot move"):
            validate_transition(STATUS_SCHEDULED, STATUS_EXPIRED, "")

    def test_overriding_an_automatic_status_without_a_reason_is_refused(self):
        with pytest.raises(TransitionError, match="reason"):
            validate_transition(STATUS_SCHEDULED, STATUS_WAITING, "   ")

    def test_overriding_an_automatic_status_with_a_reason_is_accepted(self):
        assert validate_transition(STATUS_SCHEDULED, STATUS_WAITING, "booked in error") == (
            "booked in error"
        )


class TestApplyTransition:
    def test_the_new_status_is_stored(self):
        record = entry()

        apply_transition(record, to_status=STATUS_OFFERED, now=NOW)

        assert record.status == STATUS_OFFERED

    def test_who_changed_it_and_when_are_recorded(self):
        record = entry()

        apply_transition(record, to_status=STATUS_OFFERED, actor_dbid=101, now=NOW)

        assert record.status_changed_by_id == 101
        assert record.status_changed_at == NOW

    def test_the_entry_is_saved(self):
        record = entry()

        apply_transition(record, to_status=STATUS_OFFERED, now=NOW)

        record.save.assert_called_once()

    def test_marking_scheduled_records_the_booking(self):
        record = entry()

        apply_transition(
            record, to_status=STATUS_SCHEDULED, appointment_dbid=77, now=NOW
        )

        assert record.scheduled_appointment_id == 77

    def test_leaving_scheduled_clears_the_booking_link(self):
        # Otherwise the entry keeps pointing at an appointment that no longer
        # stands.
        record = entry(status=STATUS_SCHEDULED, scheduled_appointment_id=77)

        apply_transition(
            record, to_status=STATUS_WAITING, reason="cancelled", now=NOW
        )

        assert record.scheduled_appointment_id is None

    def test_a_refused_change_leaves_the_entry_untouched(self):
        record = entry(status=STATUS_SCHEDULED)

        with pytest.raises(TransitionError):
            apply_transition(record, to_status=STATUS_EXPIRED, now=NOW)

        assert record.status == STATUS_SCHEDULED
        record.save.assert_not_called()

    def test_a_refused_change_does_not_half_write(self):
        record = entry(status=STATUS_SCHEDULED, scheduled_appointment_id=77)

        with pytest.raises(TransitionError):
            apply_transition(record, to_status=STATUS_WAITING, reason="", now=NOW)

        assert record.scheduled_appointment_id == 77
        record.save.assert_not_called()
