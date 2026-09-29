"""Tests for provider_availability.protocols.appointment_buffer."""

from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.engine.models import (
    DAYS_OF_WEEK,
    BufferTime,
    ProviderAvailabilityRule,
    TimeWindow,
)
from provider_availability.protocols.appointment_buffer import (
    BUFFER_TITLE,
    OnAppointmentCanceled,
    OnAppointmentCreated,
    OnAppointmentRescheduled,
    _create_buffer_effects,
    _delete_buffer_effects,
    _buffer_minutes,
    _covering_rules,
    _load_appointment,
    _on_appointment_canceled,
    _on_appointment_created,
    _on_appointment_rescheduled,
)


BUFFER_MODULE = "provider_availability.protocols.appointment_buffer"


_ALL_DAY = TimeWindow(start=dt_time(0, 0), end=dt_time(23, 59))
_CLINIC_HOURS = TimeWindow(start=dt_time(8, 0), end=dt_time(18, 0))


def _future_appt(minutes=30, status="confirmed", provider_id="p1", location_id="loc-1"):
    """A future appointment at a fixed hour, so an all-day window never grazes
    the window edge on a late-night test run."""
    day = (datetime.now(UTC) + timedelta(days=30)).date()
    appt = MagicMock()
    appt.id = "appt-1"
    appt.provider.id = provider_id
    appt.location.id = location_id
    appt.start_time = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
    appt.duration_minutes = minutes
    appt.status = status
    appt.appointment_rescheduled_from = None
    return appt


def _appt_on(weekday_name, hour=10, location_id="loc-1"):
    """A future appointment falling on the named weekday."""
    target = DAYS_OF_WEEK.index(weekday_name)
    day = (datetime.now(UTC) + timedelta(days=7)).date()
    while day.weekday() != target:
        day += timedelta(days=1)
    appt = MagicMock()
    appt.id = "appt-1"
    appt.provider.id = "p1"
    appt.location.id = location_id
    appt.start_time = datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)
    appt.duration_minutes = 30
    appt.status = "confirmed"
    appt.appointment_rescheduled_from = None
    return appt


def _rule(pre=15, post=15):
    """A rule covering every day, all day, so buffer tests isolate the padding."""
    return ProviderAvailabilityRule(
        id="r1",
        provider_id="p1",
        buffer_minutes=BufferTime(pre=pre, post=post),
        weekly_schedule={day: [_ALL_DAY] for day in DAYS_OF_WEEK},
    )


def _rule_on(days, pre=15, post=15, rule_id="r1", location_ids=None, active=True):
    """A rule covering only the named weekdays, 8am to 6pm."""
    return ProviderAvailabilityRule(
        id=rule_id,
        provider_id="p1",
        buffer_minutes=BufferTime(pre=pre, post=post),
        weekly_schedule={d: [_CLINIC_HOURS] for d in days},
        location_ids=list(location_ids or []),
        is_active=active,
    )


@pytest.fixture(autouse=True)
def _provider_tz_is_utc():
    """A rule's windows are written in provider-local time while an appointment
    is stored in UTC. These tests treat the provider's timezone as UTC so the
    two line up without a timezone lookup."""
    with patch(
        f"{BUFFER_MODULE}.to_provider_naive",
        side_effect=lambda dt_val, provider_id: dt_val.replace(tzinfo=None),
    ):
        yield


class TestLoadAppointment:
    def test_excludes_records_entered_in_error(self):
        """A retracted appointment never should have existed, so it gets no buffers."""
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects:
            mock_objects.filter.return_value.select_related.return_value.first.return_value = appt

            result = _load_appointment("appt-1")

            assert result is appt
            kwargs = mock_objects.filter.call_args.kwargs
            assert kwargs["id"] == "appt-1"
            assert kwargs["entered_in_error__isnull"] is True

    def test_returns_none_when_missing(self):
        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects:
            mock_objects.filter.return_value.select_related.return_value.first.return_value = None

            assert _load_appointment("appt-1") is None


class TestDeleteBufferEffects:
    def test_no_provider_returns_nothing(self):
        appt = MagicMock()
        appt.provider = None

        assert _delete_buffer_effects(appt) == []

    def test_no_admin_calendars_returns_nothing(self):
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]):
            assert _delete_buffer_effects(appt) == []

    def test_matches_by_position_not_by_id_in_title(self):
        """Pre-buffer ends when the appointment starts; post-buffer starts when it ends."""
        appt = _future_appt(minutes=30)
        start = appt.start_time
        end = start + timedelta(minutes=30)
        cal = MagicMock()
        cal.id = "cal-1"
        pre_evt = MagicMock()
        pre_evt.id = "evt-pre"
        post_evt = MagicMock()
        post_evt.id = "evt-post"

        with patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[cal]), \
             patch(f"{BUFFER_MODULE}.EventModel.objects") as mock_events:
            base = mock_events.filter.return_value
            base.filter.side_effect = [[pre_evt], [post_evt]]

            result = _delete_buffer_effects(appt)

            assert len(result) == 2
            outer = mock_events.filter.call_args.kwargs
            assert outer["calendar__id__in"] == ["cal-1"]
            assert outer["is_cancelled"] is False
            # startswith so legacy "Buffer:<id>" events are cleaned up too
            assert outer["title__startswith"] == BUFFER_TITLE
            assert [c.kwargs for c in base.filter.call_args_list] == [
                {"ends_at": start},
                {"starts_at": end},
            ]

    def test_returns_nothing_when_no_buffers_sit_at_those_times(self):
        appt = _future_appt()
        cal = MagicMock()
        cal.id = "cal-1"

        with patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[cal]), \
             patch(f"{BUFFER_MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value.filter.side_effect = [[], []]

            assert _delete_buffer_effects(appt) == []


class TestCreateBufferEffects:
    def test_no_provider_returns_nothing(self):
        appt = MagicMock()
        appt.provider = None

        assert _create_buffer_effects(appt) == []

    def test_cancelled_appointment_gets_no_buffers(self):
        appt = _future_appt(status="cancelled")

        assert _create_buffer_effects(appt) == []

    def test_zero_buffers_configured_returns_nothing(self):
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[_rule(0, 0)]):
            assert _create_buffer_effects(appt) == []

    def test_no_rules_returns_nothing(self):
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[]):
            assert _create_buffer_effects(appt) == []

    def test_past_appointment_gets_no_buffers(self):
        appt = _future_appt()
        appt.start_time = datetime.now(UTC) - timedelta(days=1)

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[_rule()]):
            assert _create_buffer_effects(appt) == []

    def test_no_admin_calendar_returns_nothing(self):
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[_rule()]), \
             patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("", [])):
            assert _create_buffer_effects(appt) == []

    def test_draws_pre_and_post_with_a_plain_title(self):
        """Nothing technical appears on the provider's calendar."""
        appt = _future_appt(minutes=30)
        start = appt.start_time
        end = start + timedelta(minutes=30)

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[_rule(15, 15)]), \
             patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.EventEffect") as mock_effect:
            result = _create_buffer_effects(appt)

            assert len(result) == 2
            drawn = [c.kwargs for c in mock_effect.call_args_list]
            assert {d["title"] for d in drawn} == {BUFFER_TITLE}
            assert drawn[0]["starts_at"] == start - timedelta(minutes=15)
            assert drawn[0]["ends_at"] == start
            assert drawn[1]["starts_at"] == end
            assert drawn[1]["ends_at"] == end + timedelta(minutes=15)

    def test_only_post_buffer_when_pre_is_zero(self):
        appt = _future_appt(minutes=30)
        end = appt.start_time + timedelta(minutes=30)

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[_rule(0, 10)]), \
             patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.EventEffect") as mock_effect:
            result = _create_buffer_effects(appt)

            assert len(result) == 1
            drawn = mock_effect.call_args.kwargs
            assert drawn["starts_at"] == end
            assert drawn["ends_at"] == end + timedelta(minutes=10)

    def test_includes_calendar_creation_effects(self):
        """A provider with no Admin calendar yet gets one created alongside."""
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[_rule()]), \
             patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", ["make-cal"])), \
             patch(f"{BUFFER_MODULE}.EventEffect"):
            result = _create_buffer_effects(appt)

            assert result[0] == "make-cal"
            assert len(result) == 3


class TestOnAppointmentCreated:
    def test_draws_buffers_for_the_new_appointment(self):
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=appt), \
             patch(f"{BUFFER_MODULE}._create_buffer_effects", side_effect=lambda a: ["drawn"]) as mock_create:
            result = _on_appointment_created("appt-1")

            assert mock_create.mock_calls == [call(appt)]
            assert result == ["drawn"]

    def test_missing_appointment_does_nothing(self):
        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=None), \
             patch(f"{BUFFER_MODULE}._create_buffer_effects") as mock_create:
            assert _on_appointment_created("appt-1") == []
            assert mock_create.mock_calls == []


class TestOnAppointmentCreatedOwnership:
    """Canvas fires APPOINTMENT_CREATED as well as APPOINTMENT_RESCHEDULED for a
    replacement appointment. Only one handler may draw, or the provider gets two
    sets of buffers at every time."""

    def test_a_replacement_is_left_to_the_reschedule_handler(self):
        replacement = _future_appt()
        replacement.appointment_rescheduled_from = _future_appt()

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=replacement), \
             patch(f"{BUFFER_MODULE}._create_buffer_effects") as mock_create:
            result = _on_appointment_created("appt-new")

            assert result == []
            assert mock_create.mock_calls == []

    def test_a_plain_booking_is_still_drawn_here(self):
        appt = _future_appt()
        appt.appointment_rescheduled_from = None

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=appt), \
             patch(f"{BUFFER_MODULE}._create_buffer_effects", side_effect=lambda a: ["drawn"]) as mock_create:
            result = _on_appointment_created("appt-1")

            assert mock_create.mock_calls == [call(appt)]
            assert result == ["drawn"]

    def test_the_two_handlers_together_draw_exactly_one_set(self):
        """A reschedule reaches both handlers. Between them they must clear the
        predecessor once and draw the replacement once."""
        previous = _future_appt()
        previous.id = "appt-old"
        replacement = _future_appt()
        replacement.appointment_rescheduled_from = previous

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=replacement), \
             patch(f"{BUFFER_MODULE}._delete_buffer_effects", side_effect=lambda a: ["gone"]) as mock_delete, \
             patch(f"{BUFFER_MODULE}._create_buffer_effects", side_effect=lambda a: ["drawn"]) as mock_create:
            from_created = _on_appointment_created("appt-new")
            from_rescheduled = _on_appointment_rescheduled("appt-new")

            assert from_created == []
            assert from_rescheduled == ["gone", "drawn"]
            assert mock_create.mock_calls == [call(replacement)]
            assert mock_delete.mock_calls == [call(previous)]


class TestOnAppointmentCanceled:
    def test_removes_only_this_appointments_buffers(self):
        appt = _future_appt()

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=appt), \
             patch(f"{BUFFER_MODULE}._delete_buffer_effects", side_effect=lambda a: ["gone"]) as mock_delete, \
             patch(f"{BUFFER_MODULE}._create_buffer_effects") as mock_create:
            result = _on_appointment_canceled("appt-1")

            assert mock_delete.mock_calls == [call(appt)]
            assert mock_create.mock_calls == []
            assert result == ["gone"]

    def test_missing_appointment_does_nothing(self):
        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=None), \
             patch(f"{BUFFER_MODULE}._delete_buffer_effects") as mock_delete:
            assert _on_appointment_canceled("appt-1") == []
            assert mock_delete.mock_calls == []


class TestOnAppointmentRescheduled:
    def test_event_carrying_the_replacement_clears_the_previous_one(self):
        """Canvas reschedule makes a new appointment; the old one's buffers must go."""
        previous = _future_appt()
        previous.id = "appt-old"
        replacement = _future_appt()
        replacement.appointment_rescheduled_from = previous

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=replacement), \
             patch(f"{BUFFER_MODULE}._delete_buffer_effects", side_effect=lambda a: ["gone"]) as mock_delete, \
             patch(f"{BUFFER_MODULE}._create_buffer_effects", side_effect=lambda a: ["drawn"]) as mock_create:
            result = _on_appointment_rescheduled("appt-new")

            assert mock_delete.mock_calls == [call(previous)]
            assert mock_create.mock_calls == [call(replacement)]
            assert result == ["gone", "drawn"]

    def test_event_carrying_the_original_finds_the_replacement(self):
        original = _future_appt()
        original.id = "appt-old"
        original.appointment_rescheduled_from = None
        replacement = _future_appt()

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=original), \
             patch(f"{BUFFER_MODULE}._delete_buffer_effects", side_effect=lambda a: ["gone"]) as mock_delete, \
             patch(f"{BUFFER_MODULE}._create_buffer_effects", side_effect=lambda a: ["drawn"]) as mock_create, \
             patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects:
            chain = mock_objects.filter.return_value.select_related.return_value
            chain.first.return_value = replacement

            result = _on_appointment_rescheduled("appt-old")

            assert mock_delete.mock_calls == [call(original)]
            assert mock_create.mock_calls == [call(replacement)]
            assert result == ["gone", "drawn"]
            # the reverse lookup also skips retracted records
            kwargs = mock_objects.filter.call_args.kwargs
            assert kwargs["appointment_rescheduled_from__id"] == original.id
            assert kwargs["entered_in_error__isnull"] is True

    def test_original_with_no_replacement_only_clears(self):
        original = _future_appt()
        original.appointment_rescheduled_from = None

        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=original), \
             patch(f"{BUFFER_MODULE}._delete_buffer_effects", side_effect=lambda a: ["gone"]), \
             patch(f"{BUFFER_MODULE}._create_buffer_effects") as mock_create, \
             patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects:
            mock_objects.filter.return_value.select_related.return_value.first.return_value = None

            result = _on_appointment_rescheduled("appt-old")

            assert mock_create.mock_calls == []
            assert result == ["gone"]

    def test_missing_appointment_does_nothing(self):
        with patch(f"{BUFFER_MODULE}._load_appointment", return_value=None), \
             patch(f"{BUFFER_MODULE}._delete_buffer_effects") as mock_delete:
            assert _on_appointment_rescheduled("appt-1") == []
            assert mock_delete.mock_calls == []


class TestProtocolHandlers:
    def test_on_appointment_created_delegates(self):
        mock_event = MagicMock()
        mock_event.target.id = "appt-1"
        handler = OnAppointmentCreated(mock_event)

        with patch(f"{BUFFER_MODULE}._on_appointment_created", return_value=[]) as mock_fn:
            result = handler.compute()

            assert mock_fn.mock_calls == [call("appt-1")]
            assert result == []

    def test_on_appointment_rescheduled_delegates(self):
        mock_event = MagicMock()
        mock_event.target.id = "appt-2"
        handler = OnAppointmentRescheduled(mock_event)

        with patch(f"{BUFFER_MODULE}._on_appointment_rescheduled", return_value=[]) as mock_fn:
            result = handler.compute()

            assert mock_fn.mock_calls == [call("appt-2")]
            assert result == []

    def test_on_appointment_canceled_delegates(self):
        mock_event = MagicMock()
        mock_event.target.id = "appt-3"
        handler = OnAppointmentCanceled(mock_event)

        with patch(f"{BUFFER_MODULE}._on_appointment_canceled", return_value=[]) as mock_fn:
            result = handler.compute()

            assert mock_fn.mock_calls == [call("appt-3")]
            assert result == []


class TestBufferMinutesFollowsTheCoveringRule:
    """Padding comes from the rule governing where the appointment sits, not
    from whichever rule happens to be stored first."""

    def test_uses_the_covering_rules_padding(self):
        appt = _appt_on("friday")
        rule = _rule_on(["friday"], pre=5, post=15)

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            assert _buffer_minutes(appt, "p1") == (5, 15)

    def test_a_rule_for_another_day_gives_no_padding(self):
        """The case that matters on a reschedule: Friday has padding, Monday
        has no rule, so a Monday appointment gets none."""
        appt = _appt_on("monday")
        friday_only = _rule_on(["friday"], pre=5, post=15)

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[friday_only]):
            assert _buffer_minutes(appt, "p1") == (0, 0)

    def test_moving_between_days_changes_the_padding(self):
        """Same provider, same two rules, opposite answers by day."""
        rules = [
            _rule_on(["friday"], pre=5, post=15, rule_id="fri"),
            _rule_on(["monday"], pre=0, post=0, rule_id="mon"),
        ]

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=rules):
            assert _buffer_minutes(_appt_on("friday"), "p1") == (5, 15)
            assert _buffer_minutes(_appt_on("monday"), "p1") == (0, 0)

    def test_a_zero_padding_rule_first_does_not_suppress_the_covering_one(self):
        """The original defect: a provider's first rule had no padding, so every
        appointment got none regardless of which rule covered it."""
        appt = _appt_on("friday")
        rules = [
            _rule_on(["monday"], pre=0, post=0, rule_id="first-and-irrelevant"),
            _rule_on(["friday"], pre=5, post=15, rule_id="covering"),
        ]

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=rules):
            assert _buffer_minutes(appt, "p1") == (5, 15)

    def test_largest_wins_when_two_rules_cover_the_same_slot(self):
        appt = _appt_on("friday")
        rules = [
            _rule_on(["friday"], pre=5, post=30, rule_id="a"),
            _rule_on(["friday"], pre=10, post=15, rule_id="b"),
        ]

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=rules):
            assert _buffer_minutes(appt, "p1") == (10, 30)

    def test_no_rules_at_all_gives_no_padding(self):
        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[]):
            assert _buffer_minutes(_appt_on("friday"), "p1") == (0, 0)

    def test_an_inactive_rule_is_ignored(self):
        appt = _appt_on("friday")
        rule = _rule_on(["friday"], pre=5, post=15, active=False)

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            assert _buffer_minutes(appt, "p1") == (0, 0)

    def test_a_rule_at_another_location_is_ignored(self):
        appt = _appt_on("friday", location_id="loc-elsewhere")
        rule = _rule_on(["friday"], pre=5, post=15, location_ids=["loc-1"])

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            assert _buffer_minutes(appt, "p1") == (0, 0)

    def test_a_rule_with_no_location_restriction_covers_any_location(self):
        appt = _appt_on("friday", location_id="loc-anything")
        rule = _rule_on(["friday"], pre=5, post=15, location_ids=[])

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            assert _buffer_minutes(appt, "p1") == (5, 15)

    def test_an_appointment_outside_the_rules_hours_gets_no_padding(self):
        appt = _appt_on("friday", hour=20)  # rule covers 8am to 6pm
        rule = _rule_on(["friday"], pre=5, post=15)

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            assert _buffer_minutes(appt, "p1") == (0, 0)

    def test_a_rule_whose_effective_range_has_ended_is_ignored(self):
        appt = _appt_on("friday")
        rule = _rule_on(["friday"], pre=5, post=15)
        rule.effective_end = (datetime.now(UTC) - timedelta(days=1)).date()

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            assert _buffer_minutes(appt, "p1") == (0, 0)

    def test_a_rule_that_has_not_started_yet_is_ignored(self):
        appt = _appt_on("friday")
        rule = _rule_on(["friday"], pre=5, post=15)
        rule.effective_start = (datetime.now(UTC) + timedelta(days=365)).date()

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            assert _buffer_minutes(appt, "p1") == (0, 0)

    def test_covering_rules_reports_which_rules_matched(self):
        appt = _appt_on("friday")
        rules = [
            _rule_on(["friday"], rule_id="fri"),
            _rule_on(["monday"], rule_id="mon"),
        ]

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=rules):
            assert [r.id for r in _covering_rules(appt, "p1")] == ["fri"]
