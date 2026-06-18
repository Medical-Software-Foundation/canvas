"""Tests for the RecurrenceInitialHandler."""

import datetime
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo

import pytest
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.note import NoteTypeCategories

from facility_recurring_scheduler.handlers.recurrence_initial import RecurrenceInitialHandler
from facility_recurring_scheduler.utils.constants import (
    INITIAL_BATCH_COUNT,
    RecurrenceEnum,
)


class TestRecurrenceInitialHandler:
    """Tests for the RecurrenceInitialHandler."""

    def test_responds_to_correct_event(self) -> None:
        """Test that the handler responds to APPOINTMENT_CREATED."""
        assert RecurrenceInitialHandler.RESPONDS_TO == EventType.Name(
            EventType.APPOINTMENT_CREATED
        )

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_creates_daily_recurrence_batch_for_schedule_event(
        self, mock_appointment_model, mock_metadata, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test daily recurrence creates 60 initial child events for schedule events."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {"patient": {"id": "patient-456"}}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "daily"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 1, 2, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        # Should create 60 child events for daily recurrence
        assert len(effects) == INITIAL_BATCH_COUNT["daily"]

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_creates_weekly_recurrence_batch_for_schedule_event(
        self, mock_appointment_model, mock_metadata, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test weekly recurrence creates 8 initial child events for schedule events."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {"patient": {"id": "patient-456"}}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "weekly"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 1, 8, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert len(effects) == INITIAL_BATCH_COUNT["weekly"]

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_creates_monthly_recurrence_batch_for_schedule_event(
        self, mock_appointment_model, mock_metadata, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test monthly recurrence creates 2 initial child events for schedule events."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {"patient": {"id": "patient-456"}}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "monthly"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 2, 1, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert len(effects) == INITIAL_BATCH_COUNT["monthly"]

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.Appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_creates_weekly_recurrence_for_regular_appointment(
        self, mock_appointment_model, mock_metadata, mock_appointment_effect, mock_calc_date, mock_get_tz
    ) -> None:
        """Test weekly recurrence creates child events for regular appointments."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {"patient": {"id": "patient-456"}}

        # Regular appointment (not schedule event)
        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = "encounter"  # Not a schedule event
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment.meeting_link = "https://example.com/meeting"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "weekly"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 1, 8, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_appointment_effect.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        # Should create 8 child appointments for weekly recurrence
        assert len(effects) == INITIAL_BATCH_COUNT["weekly"]

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_creates_every_2_weeks_recurrence_batch(
        self, mock_appointment_model, mock_metadata, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test every-2-weeks recurrence creates 4 initial child events."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {"patient": {"id": "patient-456"}}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "every 2 weeks"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 1, 15, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert len(effects) == INITIAL_BATCH_COUNT["every 2 weeks"]

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_creates_every_3_weeks_recurrence_batch(
        self, mock_appointment_model, mock_metadata, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test every-3-weeks recurrence creates 3 initial child events."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {"patient": {"id": "patient-456"}}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "every 3 weeks"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 1, 22, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert len(effects) == INITIAL_BATCH_COUNT["every 3 weeks"]

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_no_children_for_none_recurrence(
        self, mock_appointment_model, mock_metadata
    ) -> None:
        """Test no children created when recurrence is 'none'."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "none"
        )

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert effects == []

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_no_children_for_missing_recurrence(
        self, mock_appointment_model, mock_metadata
    ) -> None:
        """Test no children created when recurrence metadata is missing."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            None
        )

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert effects == []

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_skips_child_events(self, mock_appointment_model) -> None:
        """Test handler skips child events (those with parent_appointment_id)."""
        mock_event = MagicMock()
        mock_event.target.id = "child-123"

        mock_appointment = MagicMock()
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.parent_appointment_id = "parent-456"  # This is a child
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        # Verify appointment was fetched
        mock_appointment_model.objects.select_related.return_value.get.assert_called_once_with(id="child-123")

        assert effects == []

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_child_event_has_parent_appointment_id(
        self, mock_appointment_model, mock_metadata, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test that child events are created with parent_appointment_id."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "weekly"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 1, 8, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        handler.compute()

        # Verify ScheduleEvent was called with parent_appointment_id
        for call_item in mock_schedule_event.call_args_list:
            assert call_item.kwargs.get("parent_appointment_id") == "parent-123"

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.get_timezone_for_appointment")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_timezone_resolved_once_and_cached(
        self, mock_appointment_model, mock_metadata, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test that timezone is resolved once per compute() call, not per iteration."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {"patient": {"id": "patient-456"}}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment.start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        mock_appointment.duration_minutes = 60
        mock_appointment.location.id = "loc-1"
        mock_appointment.provider.id = "prov-1"
        mock_appointment.note_type.id = "note-type-1"
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "daily"
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")
        mock_calc_date.return_value = datetime.datetime(2024, 1, 2, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        handler = RecurrenceInitialHandler(mock_event)
        handler.compute()

        # Timezone should be resolved exactly once, not 60 times
        mock_get_tz.assert_called_once_with(mock_appointment, "patient-456")

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.log")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_does_not_exist_handled_gracefully(
        self, mock_appointment_model, mock_log
    ) -> None:
        """Test that DoesNotExist is handled gracefully when appointment is missing."""
        mock_event = MagicMock()
        mock_event.target.id = "missing-123"

        mock_appointment_model.DoesNotExist = Exception
        mock_appointment_model.objects.select_related.return_value.get.side_effect = Exception("not found")

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert effects == []
        mock_log.warning.assert_called()

    @patch("facility_recurring_scheduler.handlers.recurrence_initial.log")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.recurrence_initial.AppointmentModel")
    def test_unknown_recurrence_returns_empty(
        self, mock_appointment_model, mock_metadata, mock_log
    ) -> None:
        """Test that unknown recurrence types return empty and log a warning."""
        mock_event = MagicMock()
        mock_event.target.id = "parent-123"
        mock_event.context = {}

        mock_appointment = MagicMock()
        mock_appointment.id = "parent-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "biweekly"
        )

        handler = RecurrenceInitialHandler(mock_event)
        effects = handler.compute()

        assert effects == []
        mock_log.warning.assert_called()
