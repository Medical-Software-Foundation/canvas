"""Tests for provider_availability.protocols.appointment_buffer."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

from provider_availability.engine.models import BufferTime, ProviderAvailabilityRule
from provider_availability.protocols.appointment_buffer import (
    DEFAULT_HORIZON_YEARS,
    OnAppointmentCanceled,
    OnAppointmentCreated,
    OnAppointmentRescheduled,
    _reconcile_buffers,
    reconcile_buffers_for_provider,
)


BUFFER_MODULE = "provider_availability.protocols.appointment_buffer"


def _cal(cal_id):
    """Build a stub admin calendar exposing an ``id``."""
    c = MagicMock()
    c.id = cal_id
    return c


def _event(event_id):
    """Build a stub calendar Event exposing an ``id``."""
    e = MagicMock()
    e.id = event_id
    return e


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

    def test_no_rules_deletes_existing_and_creates_none(self):
        """No rule → provider has no buffer, so existing holds are cleared, none created."""
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[_cal("c1")]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id") as mock_get_or_create, \
             patch(f"{BUFFER_MODULE}.EventModel.objects") as mock_events:
            mock_objects.get.return_value = mock_appt
            mock_events.filter.return_value = [_event("e1"), _event("e2")]

            result = _reconcile_buffers("appt-1", "created")

            # Two existing holds deleted, nothing recreated, no calendar get-or-create.
            assert len(result) == 2
            mock_get_or_create.assert_not_called()

    def test_zero_buffers_deletes_existing_and_creates_none(self):
        """Zeroed buffer → existing holds are deleted (the removal-bug fix), none created."""
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=0, post=0),
        )

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[_cal("c1")]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id") as mock_get_or_create, \
             patch(f"{BUFFER_MODULE}.EventModel.objects") as mock_events:
            mock_objects.get.return_value = mock_appt
            mock_events.filter.return_value = [_event("e1"), _event("e2"), _event("e3")]

            result = _reconcile_buffers("appt-1", "created")

            assert len(result) == 3  # three stale holds deleted
            mock_get_or_create.assert_not_called()  # recreation path never entered

    def test_zero_buffers_no_existing_holds_is_noop(self):
        mock_appt = MagicMock()
        mock_appt.provider.id = "p1"

        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=0, post=0),
        )

        with patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_objects, \
             patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]):
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
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("", [])), \
             patch(f"{BUFFER_MODULE}.EventModel.objects"):
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

    def test_deletes_then_recreates_when_buffer_present(self):
        """With a buffer configured and existing holds: delete all, then recreate."""
        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=0, post=15),
        )

        future_appt = MagicMock()
        future_appt.start_time = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
        future_appt.duration_minutes = 30
        future_appt.status = "confirmed"

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[_cal("c1")]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_appt_objects, \
             patch(f"{BUFFER_MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value = [_event("e1"), _event("e2")]
            mock_appt_objects.filter.return_value.exclude.return_value = [future_appt]

            result = reconcile_buffers_for_provider("p1", "rule_saved")

            # 2 stale holds deleted + 1 post-buffer create (pre=0 → no pre create)
            assert len(result) == 3

    def test_query_excludes_schedule_events_and_caps_horizon(self):
        """Recreation must only consider patient visits within the bounded horizon.

        Without these bounds, no-end recurring schedule events (lunch, blocks, OOO —
        all patientless) generate buffers decades into the future.
        """
        rule = ProviderAvailabilityRule(
            id="r1", provider_id="p1",
            buffer_minutes=BufferTime(pre=15, post=15),
        )

        with patch(f"{BUFFER_MODULE}.get_rules_for_provider", return_value=[rule]), \
             patch(f"{BUFFER_MODULE}.get_admin_calendar_id", return_value=("cal-1", [])), \
             patch(f"{BUFFER_MODULE}.get_admin_calendars", return_value=[]), \
             patch(f"{BUFFER_MODULE}.Appointment.objects") as mock_appt_objects, \
             patch(f"{BUFFER_MODULE}.EventModel.objects"):
            mock_appt_objects.filter.return_value.exclude.return_value = []

            reconcile_buffers_for_provider("p1", "rule_saved")

            kwargs = mock_appt_objects.filter.call_args.kwargs
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
