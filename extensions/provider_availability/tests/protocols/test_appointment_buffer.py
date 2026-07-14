"""Tests for provider_availability.protocols.appointment_buffer."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call, patch

from provider_availability.engine.models import BufferTime, ProviderAvailabilityRule
from provider_availability.protocols.appointment_buffer import (
    BUFFER_TITLE,
    DEFAULT_HORIZON_YEARS,
    OnAppointmentCanceled,
    OnAppointmentCreated,
    OnAppointmentRescheduled,
    _reconcile_buffers,
)


BUFFER_MODULE = "provider_availability.protocols.appointment_buffer"


class TestReconcileBuffers:
    def test_appointment_not_found(self):
        from canvas_sdk.v1.data.appointment import Appointment

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects:
            mock_objects.get.side_effect = Appointment.DoesNotExist

            result = _reconcile_buffers("appt-1", "created")

            assert mock_objects.mock_calls == [call.get(id="appt-1")]
            assert result == []

    def test_no_provider(self):
        mock_appt = MagicMock()
        mock_appt.provider = None

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects:
            mock_objects.get.return_value = mock_appt

            result = _reconcile_buffers("appt-1", "created")

            assert result == []

    def test_no_rules_for_provider(self):
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[]):
            mock_objects.get.return_value = mock_appt

            result = _reconcile_buffers("appt-1", "created")

            assert result == []

    def test_zero_buffers_skips(self):
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=0, post=0),
        )

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]):
            mock_objects.get.return_value = mock_appt

            result = _reconcile_buffers("appt-1", "created")

            assert result == []

    def test_no_admin_calendar(self):
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=15, post=15),
        )

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("", [])):
            mock_objects.get.return_value = mock_appt

            result = _reconcile_buffers("appt-1", "created")

            assert result == []

    def test_creates_buffer_events(self):
        """Buffer events should be created for future appointments."""
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=15, post=15),
        )

        future_appt = MagicMock()
        future_appt.start_time = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
        future_appt.duration_minutes = 30
        future_appt.status = "confirmed"

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]), \
             patch(f"{BUFFER_MODULE}.EventModel.objects"):
            mock_objects.get.return_value = mock_appt
            mock_objects.filter.return_value.exclude.return_value = [future_appt]

            result = _reconcile_buffers("appt-1", "created")

            # Should create pre-buffer + post-buffer events
            assert len(result) == 2  # pre + post

    def test_query_excludes_schedule_events_and_caps_horizon(self):
        """Buffer reconciliation must only consider patient visits within the horizon.

        Without these bounds, no-end recurring schedule events (lunch, blocks, OOO —
        all patientless) generate buffers decades into the future, producing millions
        of effects.
        """
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=15, post=15),
        )

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]), \
             patch(f"{BUFFER_MODULE}.EventModel.objects"):
            mock_objects.get.return_value = mock_appt
            mock_objects.filter.return_value.exclude.return_value = []

            _reconcile_buffers("appt-1", "created")

            kwargs = mock_objects.filter.call_args.kwargs
            # Schedule events (no patient) are excluded
            assert kwargs["patient__isnull"] is False
            # The query is bounded on both ends
            lower = kwargs["start_time__gte"]
            upper = kwargs["start_time__lte"]
            assert upper.year == lower.year + DEFAULT_HORIZON_YEARS
            assert upper > lower


class TestProtocolHandlers:
    def test_on_appointment_created_delegates(self):
        mock_event = MagicMock()
        mock_event.target.id = "appt-1"
        handler = OnAppointmentCreated(mock_event)

        with patch(f"{BUFFER_MODULE}._reconcile_buffers", return_value=[]) as mock_reconcile:
            result = handler.compute()

            assert mock_reconcile.mock_calls == [call("appt-1", "created")]
            assert result == []

    def test_on_appointment_rescheduled_delegates(self):
        mock_event = MagicMock()
        mock_event.target.id = "appt-2"
        handler = OnAppointmentRescheduled(mock_event)

        with patch(f"{BUFFER_MODULE}._reconcile_buffers", return_value=[]) as mock_reconcile:
            result = handler.compute()

            assert mock_reconcile.mock_calls == [call("appt-2", "rescheduled")]
            assert result == []

    def test_on_appointment_canceled_delegates(self):
        mock_event = MagicMock()
        mock_event.target.id = "appt-3"
        handler = OnAppointmentCanceled(mock_event)

        with patch(f"{BUFFER_MODULE}._reconcile_buffers", return_value=[]) as mock_reconcile:
            result = handler.compute()

            assert mock_reconcile.mock_calls == [call("appt-3", "canceled")]
            assert result == []
