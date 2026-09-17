"""Tests for provider_availability.protocols.appointment_buffer."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call, patch

from provider_availability.engine.models import BufferTime, ProviderAvailabilityRule
from provider_availability.protocols.appointment_buffer import (
    BUFFER_TITLE,
    OnAppointmentCanceled,
    OnAppointmentCreated,
    OnAppointmentRescheduled,
    _create_buffer_effects,
    _delete_buffer_effects,
    _load_appointment,
    _on_appointment_canceled,
    _on_appointment_created,
    _on_appointment_rescheduled,
)


BUFFER_MODULE = "provider_availability.protocols.appointment_buffer"


def _future_appt(minutes=30, status="confirmed", provider_id="p1"):
    appt = MagicMock()
    appt.provider.id = provider_id
    appt.start_time = datetime.now(UTC) + timedelta(days=30)
    appt.duration_minutes = minutes
    appt.status = status
    return appt


def _rule(pre=15, post=15):
    return ProviderAvailabilityRule(
        id="r1", provider_id="p1", buffer_minutes=BufferTime(pre=pre, post=post)
    )


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
