"""Tests for provider_availability.protocols.appointment_buffer."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call, patch

from provider_availability.engine.models import BufferTime, ProviderAvailabilityRule
from provider_availability.protocols.appointment_buffer import (
    BUFFER_TITLE,
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

    def _future_appt(self, minutes=30, status="confirmed"):
        appt = MagicMock()
        appt.provider.id = "p1"
        appt.start_time = datetime.now(UTC) + timedelta(days=30)
        appt.duration_minutes = minutes
        appt.status = status
        return appt

    def _rule(self, pre=15, post=15):
        return ProviderAvailabilityRule(
            id="r1", provider_id="p1", buffer_minutes=BufferTime(pre=pre, post=post),
        )

    def test_no_admin_calendar(self):
        appt = self._future_appt()

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[self._rule()]), \
             patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("", [])):
            mock_objects.get.return_value = appt

            result = _reconcile_buffers("appt-1", "created")

            assert result == []

    def test_creates_buffers_with_clean_title(self):
        """Buffers are rebuilt for future appointments with a plain 'Buffer' title (no id)."""
        appt = self._future_appt()

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[self._rule()]), \
             patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]), \
             patch(f"{BUFFER_MODULE}.EventModel.objects"), \
             patch(f"{BUFFER_MODULE}.EventEffect") as mock_event_effect:
            mock_objects.get.return_value = appt
            mock_objects.filter.return_value.exclude.return_value = [appt]

            result = _reconcile_buffers("appt-1", "created")

            # pre + post
            assert len(result) == 2
            titles = {c.kwargs["title"] for c in mock_event_effect.call_args_list}
            assert titles == {"Buffer"}

    def test_rebuild_deletes_existing_buffers_then_recreates_from_current_appts(self):
        """Delete all existing buffers (incl. legacy tagged) and rebuild from current appts."""
        appt = self._future_appt()
        existing = MagicMock()
        existing.id = "evt-9"
        cal = MagicMock()
        cal.id = "cal-1"

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[self._rule()]), \
             patch(f"{BUFFER_MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[cal]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.EventModel.objects") as mock_events:
            mock_objects.get.return_value = appt
            mock_events.filter.return_value = [existing]
            # no current future appointments → nothing recreated
            mock_objects.filter.return_value.exclude.return_value = []

            result = _reconcile_buffers("appt-1", "canceled")

            # one delete effect, no recreations
            assert len(result) == 1
            # deletion matches any Buffer-prefixed title (cleans legacy tagged ones)
            assert mock_events.filter.call_args.kwargs["title__startswith"] == "Buffer"


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
