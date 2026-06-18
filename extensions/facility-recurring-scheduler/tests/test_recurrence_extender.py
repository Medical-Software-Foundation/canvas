"""Tests for the RecurrenceExtender CronTask."""

import datetime
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo

import pytest
from canvas_sdk.v1.data.note import NoteTypeCategories

from facility_recurring_scheduler.handlers.recurrence_extender import RecurrenceExtender
from facility_recurring_scheduler.utils.constants import (
    TARGET_HORIZON_DAYS,
    FIELD_RECURRENCE_KEY,
    RecurrenceEnum,
)


class TestRecurrenceExtender:
    """Tests for the RecurrenceExtender CronTask."""

    def test_schedule_is_daily_midnight(self) -> None:
        """Test that the cron schedule is set to daily at midnight."""
        assert RecurrenceExtender.SCHEDULE == "0 0 * * *"

    def test_target_horizon_is_90_days(self) -> None:
        """Test that target horizon is configured for 3 months (90 days)."""
        assert TARGET_HORIZON_DAYS == 90

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_extends_weekly_schedule_events_to_reach_horizon(
        self, mock_metadata, mock_appointment_model, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test that weekly schedule events are extended to reach the 90-day horizon."""
        mock_event = MagicMock()
        now = datetime.datetime.now(datetime.timezone.utc)

        # Mock parent appointment (schedule event)
        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.start_time = now - datetime.timedelta(days=30)
        mock_parent.duration_minutes = 60
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-type-1"
        mock_parent.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_parent.patient = None

        # Latest child is 60 days from now (needs ~5 more weeks to reach 90)
        latest_child_time = now + datetime.timedelta(days=60)

        # Setup parent IDs query (first filter call)
        mock_parent_ids_queryset = MagicMock()
        mock_parent_ids_queryset.exclude.return_value.values_list.return_value = [
            "parent-123"
        ]

        # Setup batch metadata query for recurrence patterns
        mock_recurrence_queryset = MagicMock()
        mock_recurrence_queryset.values_list.return_value = [("parent-123", "weekly")]

        # Setup batch children query for latest children
        mock_children_queryset = MagicMock()
        mock_children_values = MagicMock()
        mock_children_values.annotate.return_value = [
            {"parent_appointment_id": "parent-123", "latest_start": latest_child_time}
        ]
        mock_children_queryset.exclude.return_value.values.return_value = mock_children_values

        # Setup parent appointment query with select_related
        mock_parent_queryset = MagicMock()
        mock_select_related = MagicMock()
        mock_select_related.__iter__ = lambda self: iter([mock_parent])
        mock_parent_queryset.exclude.return_value.select_related.return_value = mock_select_related

        def metadata_filter_side_effect(**kwargs):
            if "key" in kwargs and kwargs["key"] == FIELD_RECURRENCE_KEY:
                if "appointment_id__in" in kwargs:
                    return mock_recurrence_queryset
                else:
                    return mock_parent_ids_queryset
            return MagicMock()

        def appointment_filter_side_effect(**kwargs):
            if "id__in" in kwargs:
                return mock_parent_queryset
            if "parent_appointment_id__in" in kwargs:
                return mock_children_queryset
            return MagicMock()

        mock_metadata.objects.filter.side_effect = metadata_filter_side_effect
        mock_appointment_model.objects.filter.side_effect = appointment_filter_side_effect

        mock_get_tz.return_value = ZoneInfo("America/New_York")

        # Simulate weekly dates: 67, 74, 81, 88 days from now, then 95 (past horizon)
        target_date = now + datetime.timedelta(days=TARGET_HORIZON_DAYS)
        call_count = 0
        def calc_date_side_effect(start_time, count, recurrence, local_tz):
            return latest_child_time + datetime.timedelta(weeks=count)
        mock_calc_date.side_effect = calc_date_side_effect

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender.execute()

        # Should create events to reach 90-day horizon
        assert len(effects) >= 4

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_no_extension_when_no_recurring_parents(
        self, mock_metadata, mock_appointment_model
    ) -> None:
        """Test that no events are created when there are no recurring parents."""
        mock_event = MagicMock()

        # No parents with recurrence - return empty list
        mock_parent_ids_queryset = MagicMock()
        mock_parent_ids_queryset.exclude.return_value.values_list.return_value = []

        # Empty parent query result
        mock_parent_queryset = MagicMock()
        mock_select_related = MagicMock()
        mock_select_related.__iter__ = lambda self: iter([])
        mock_parent_queryset.exclude.return_value.select_related.return_value = mock_select_related

        mock_metadata.objects.filter.return_value = mock_parent_ids_queryset
        mock_appointment_model.objects.filter.return_value = mock_parent_queryset

        extender = RecurrenceExtender(mock_event)
        effects = extender.execute()

        assert effects == []

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.log")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_does_not_regenerate_when_all_children_cancelled(
        self, mock_metadata, mock_appointment_model, mock_schedule_event,
        mock_calc_date, mock_get_tz, mock_log
    ) -> None:
        """A series whose children were all cancelled must NOT be regenerated.

        When every child of a recurring parent is cancelled/noshow,
        _batch_get_latest_children returns no entry for that parent. The
        extender must skip it rather than falling back to parent.start_time
        and recreating events the user deliberately cancelled.
        """
        mock_event = MagicMock()
        now = datetime.datetime.now(datetime.timezone.utc)

        # Parent is still active and recurring, but all its children are cancelled
        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.start_time = now - datetime.timedelta(days=30)
        mock_parent.note_type.category = NoteTypeCategories.SCHEDULE_EVENT

        mock_parent_ids_queryset = MagicMock()
        mock_parent_ids_queryset.exclude.return_value.values_list.return_value = ["parent-123"]

        mock_recurrence_queryset = MagicMock()
        mock_recurrence_queryset.values_list.return_value = [("parent-123", "weekly")]

        # No active children — aggregation returns nothing for this parent
        mock_children_queryset = MagicMock()
        mock_children_values = MagicMock()
        mock_children_values.annotate.return_value = []
        mock_children_queryset.exclude.return_value.values.return_value = mock_children_values

        mock_parent_queryset = MagicMock()
        mock_select_related = MagicMock()
        mock_select_related.__iter__ = lambda self: iter([mock_parent])
        mock_parent_queryset.exclude.return_value.select_related.return_value = mock_select_related

        def metadata_filter_side_effect(**kwargs):
            if "key" in kwargs and kwargs["key"] == FIELD_RECURRENCE_KEY:
                if "appointment_id__in" in kwargs:
                    return mock_recurrence_queryset
                return mock_parent_ids_queryset
            return MagicMock()

        def appointment_filter_side_effect(**kwargs):
            if "id__in" in kwargs:
                return mock_parent_queryset
            if "parent_appointment_id__in" in kwargs:
                return mock_children_queryset
            return MagicMock()

        mock_metadata.objects.filter.side_effect = metadata_filter_side_effect
        mock_appointment_model.objects.filter.side_effect = appointment_filter_side_effect
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        extender = RecurrenceExtender(mock_event)
        effects = extender.execute()

        # No events recreated, and no date calculation attempted for this parent
        assert effects == []
        mock_calc_date.assert_not_called()
        mock_schedule_event.assert_not_called()

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    def test_create_events_to_horizon_every_2_weeks(self, mock_calc_date, mock_get_tz, mock_schedule_event) -> None:
        """Test that every-2-weeks events are extended to the horizon correctly."""
        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        now = datetime.datetime.now(datetime.timezone.utc)
        start = now + datetime.timedelta(days=1)

        def side_effect(start_time, count, recurrence, local_tz):
            return start + datetime.timedelta(weeks=2 * count)
        mock_calc_date.side_effect = side_effect

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-1"
        mock_parent.patient = None

        # Target 8 weeks out — should create 4 events (at weeks 2, 4, 6, 8)
        target = start + datetime.timedelta(weeks=8)

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, start, target, "every 2 weeks", is_schedule_event=True
        )

        assert len(effects) == 4

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    def test_calculate_next_date_daily(self, mock_calc_date, mock_get_tz, mock_schedule_event) -> None:
        """Test that _create_events_to_horizon calls calculate_recurrence_date correctly."""
        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        now = datetime.datetime.now(datetime.timezone.utc)
        start = now + datetime.timedelta(days=1)
        # Simulate 7 daily dates, then one past target
        def side_effect(start_time, count, recurrence, local_tz):
            return start + datetime.timedelta(days=count)
        mock_calc_date.side_effect = side_effect

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-1"
        mock_parent.patient = None

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        target = start + datetime.timedelta(days=7)

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, start, target, "daily", is_schedule_event=True
        )

        assert len(effects) == 7

    def test_months_between(self) -> None:
        """_months_between counts whole calendar months in local time."""
        extender = RecurrenceExtender(MagicMock())
        tz = ZoneInfo("America/New_York")
        jan = datetime.datetime(2024, 1, 10, 14, 0, tzinfo=ZoneInfo("UTC"))
        apr = datetime.datetime(2024, 4, 10, 14, 0, tzinfo=ZoneInfo("UTC"))
        next_year = datetime.datetime(2025, 2, 10, 14, 0, tzinfo=ZoneInfo("UTC"))
        assert extender._months_between(jan, apr, tz) == 3
        assert extender._months_between(jan, jan, tz) == 0
        assert extender._months_between(jan, next_year, tz) == 13
        # Never negative if later precedes anchor
        assert extender._months_between(apr, jan, tz) == 0

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    def test_monthly_extension_anchors_on_parent_start(
        self, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Monthly extension anchors date calculation on the parent's original
        start_time (fixing drift), not on the latest child, and resumes at the
        occurrence index near last_date rather than iterating from month 1."""
        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")
        now = datetime.datetime.now(datetime.timezone.utc)

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        # Parent anchored ~4 months in the past
        mock_parent.start_time = now - datetime.timedelta(days=120)
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-1"
        mock_parent.patient = None

        last_date = now + datetime.timedelta(days=2)
        target_date = now + datetime.timedelta(days=TARGET_HORIZON_DAYS)

        def side_effect(start_time, count, recurrence, local_tz):
            # Monthly-ish dates measured from the anchor that was passed in
            return start_time + datetime.timedelta(days=30 * count)
        mock_calc_date.side_effect = side_effect

        mock_schedule_event.return_value = MagicMock()

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, last_date, target_date, "monthly", is_schedule_event=True
        )

        # Every date calculation used the parent's start_time as the anchor,
        # never the latest child (last_date) — this is what eliminates drift.
        assert mock_calc_date.call_args_list, "expected calculate_recurrence_date to be called"
        for c in mock_calc_date.call_args_list:
            assert c.args[0] == mock_parent.start_time

        # Resumed near last_date rather than from month 1
        first_count = mock_calc_date.call_args_list[0].args[1]
        expected_start = extender._months_between(
            mock_parent.start_time, last_date, ZoneInfo("America/New_York")
        ) + 1
        assert first_count == expected_start

        # Produced the future occurrences up to the horizon
        assert len(effects) > 0

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_get_active_recurring_parents_excludes_none_recurrence(
        self, mock_metadata, mock_appointment_model
    ) -> None:
        """Test that parents with 'none' recurrence are excluded."""
        mock_event = MagicMock()

        # Setup the metadata query
        mock_queryset = MagicMock()
        mock_exclude_queryset = MagicMock()
        mock_exclude_queryset.values_list.return_value = ["parent-123"]
        mock_queryset.exclude.return_value = mock_exclude_queryset
        mock_metadata.objects.filter.return_value = mock_queryset

        # Setup parent query with select_related
        mock_parent_queryset = MagicMock()
        mock_exclude_result = MagicMock()
        mock_select_related = MagicMock()
        mock_select_related.__iter__ = lambda self: iter([])
        mock_exclude_result.select_related.return_value = mock_select_related
        mock_parent_queryset.exclude.return_value = mock_exclude_result
        mock_appointment_model.objects.filter.return_value = mock_parent_queryset

        extender = RecurrenceExtender(mock_event)
        extender._get_active_recurring_parents()

        # Verify that exclude was called with none value
        mock_queryset.exclude.assert_called_once_with(value=RecurrenceEnum.NONE.value)

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    def test_create_child_schedule_event_without_description(
        self, mock_schedule_event
    ) -> None:
        """Test that child schedule events are created without description."""
        mock_event = MagicMock()
        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 60
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-type-1"
        mock_parent.patient = None

        start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))

        extender = RecurrenceExtender(mock_event)
        extender._create_child_schedule_event(mock_parent, start_time)

        # Verify ScheduleEvent was called without description
        mock_schedule_event.assert_called_once()
        call_kwargs = mock_schedule_event.call_args.kwargs
        assert "description" not in call_kwargs
        assert call_kwargs["parent_appointment_id"] == "parent-123"
        assert call_kwargs["start_time"] == start_time
        assert call_kwargs["duration_minutes"] == 60
        assert call_kwargs["practice_location_id"] == "loc-1"
        assert call_kwargs["provider_id"] == "prov-1"
        assert call_kwargs["note_type_id"] == "note-type-1"

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    def test_create_child_schedule_event_includes_patient_id(
        self, mock_schedule_event
    ) -> None:
        """Test that child schedule events include patient_id from parent."""
        mock_event = MagicMock()
        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 60
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-type-1"
        mock_parent.patient.id = "patient-789"

        start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))

        extender = RecurrenceExtender(mock_event)
        extender._create_child_schedule_event(mock_parent, start_time)

        call_kwargs = mock_schedule_event.call_args.kwargs
        assert call_kwargs["patient_id"] == "patient-789"

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.Appointment")
    def test_create_child_appointment_for_regular_appointments(
        self, mock_appointment
    ) -> None:
        """Test that child appointments are created for regular appointments."""
        mock_event = MagicMock()
        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-type-1"
        mock_parent.meeting_link = "https://example.com/meeting"
        mock_parent.patient.id = "patient-456"

        start_time = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))

        extender = RecurrenceExtender(mock_event)
        extender._create_child_appointment(mock_parent, start_time)

        # Verify Appointment was called with correct parameters
        mock_appointment.assert_called_once()
        call_kwargs = mock_appointment.call_args.kwargs
        assert call_kwargs["patient_id"] == "patient-456"
        assert call_kwargs["parent_appointment_id"] == "parent-123"
        assert call_kwargs["start_time"] == start_time
        assert call_kwargs["duration_minutes"] == 30
        assert call_kwargs["meeting_link"] == "https://example.com/meeting"

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    def test_create_events_to_horizon_stops_at_target(
        self, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test that event creation stops when target date is reached."""
        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-1"
        mock_parent.patient = None

        now = datetime.datetime.now(datetime.timezone.utc)
        last_date = now + datetime.timedelta(days=1)
        target_date = last_date + datetime.timedelta(days=7)  # 7 days

        def side_effect(start_time, count, recurrence, local_tz):
            return last_date + datetime.timedelta(days=count)
        mock_calc_date.side_effect = side_effect

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, last_date, target_date, "daily", is_schedule_event=True
        )

        # Should create 7 events (days 1-7)
        assert len(effects) == 7

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.Appointment")
    def test_create_events_to_horizon_for_regular_appointments(
        self, mock_appointment, mock_calc_date, mock_get_tz
    ) -> None:
        """Test event creation works for regular appointments."""
        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-1"
        mock_parent.meeting_link = "https://example.com"
        mock_parent.patient.id = "patient-456"

        now = datetime.datetime.now(datetime.timezone.utc)
        last_date = now + datetime.timedelta(days=1)
        target_date = last_date + datetime.timedelta(weeks=2)  # 2 weeks

        def side_effect(start_time, count, recurrence, local_tz):
            return last_date + datetime.timedelta(weeks=count)
        mock_calc_date.side_effect = side_effect

        mock_effect = MagicMock()
        mock_appointment.return_value = mock_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, last_date, target_date, "weekly", is_schedule_event=False
        )

        # Should create 2 events (weeks 1 and 2)
        assert len(effects) == 2

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_execute_skips_none_recurrence(
        self, mock_metadata, mock_appointment_model
    ) -> None:
        """Test that events with 'none' recurrence are skipped in execute."""
        mock_event = MagicMock()
        now = datetime.datetime.now(datetime.timezone.utc)

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.start_time = now

        # Setup parent IDs query
        mock_parent_ids_queryset = MagicMock()
        mock_parent_ids_queryset.exclude.return_value.values_list.return_value = [
            "parent-123"
        ]

        # Setup batch metadata query for recurrence patterns - return "none"
        mock_recurrence_queryset = MagicMock()
        mock_recurrence_queryset.values_list.return_value = [("parent-123", "none")]

        # Setup parent appointment query with select_related
        mock_parent_queryset = MagicMock()
        mock_select_related = MagicMock()
        mock_select_related.__iter__ = lambda self: iter([mock_parent])
        mock_parent_queryset.exclude.return_value.select_related.return_value = mock_select_related

        def metadata_filter_side_effect(**kwargs):
            if "key" in kwargs and kwargs["key"] == FIELD_RECURRENCE_KEY:
                if "appointment_id__in" in kwargs:
                    return mock_recurrence_queryset
                else:
                    return mock_parent_ids_queryset
            return MagicMock()

        def appointment_filter_side_effect(**kwargs):
            if "id__in" in kwargs:
                return mock_parent_queryset
            return MagicMock()

        mock_metadata.objects.filter.side_effect = metadata_filter_side_effect
        mock_appointment_model.objects.filter.side_effect = appointment_filter_side_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender.execute()

        # Should return empty because recurrence is "none"
        assert effects == []

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_batch_get_recurrence_patterns(self, mock_metadata) -> None:
        """Test batch fetching of recurrence patterns."""
        mock_event = MagicMock()

        mock_queryset = MagicMock()
        mock_queryset.values_list.return_value = [
            ("parent-1", "daily"),
            ("parent-2", "weekly"),
            ("parent-3", "monthly"),
        ]
        mock_metadata.objects.filter.return_value = mock_queryset

        extender = RecurrenceExtender(mock_event)
        result = extender._batch_get_recurrence_patterns(["parent-1", "parent-2", "parent-3"])

        assert result == {
            "parent-1": "daily",
            "parent-2": "weekly",
            "parent-3": "monthly",
        }
        mock_metadata.objects.filter.assert_called_once_with(
            appointment_id__in=["parent-1", "parent-2", "parent-3"],
            key=FIELD_RECURRENCE_KEY,
        )

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    def test_batch_get_latest_children(self, mock_appointment_model) -> None:
        """Test batch fetching of latest child start times excludes cancelled/noshow."""
        mock_event = MagicMock()
        now = datetime.datetime.now(datetime.timezone.utc)

        time1 = now + datetime.timedelta(days=30)
        time2 = now + datetime.timedelta(days=60)

        mock_queryset = MagicMock()
        mock_exclude_queryset = MagicMock()
        mock_values = MagicMock()
        mock_values.annotate.return_value = [
            {"parent_appointment_id": "parent-1", "latest_start": time1},
            {"parent_appointment_id": "parent-2", "latest_start": time2},
        ]
        mock_exclude_queryset.values.return_value = mock_values
        mock_queryset.exclude.return_value = mock_exclude_queryset
        mock_appointment_model.objects.filter.return_value = mock_queryset

        extender = RecurrenceExtender(mock_event)
        result = extender._batch_get_latest_children(["parent-1", "parent-2"])

        assert result == {
            "parent-1": time1,
            "parent-2": time2,
        }
        mock_appointment_model.objects.filter.assert_called_once_with(
            parent_appointment_id__in=["parent-1", "parent-2"]
        )
        mock_queryset.exclude.assert_called_once_with(
            status__in=["cancelled", "noshow"]
        )
        mock_exclude_queryset.values.assert_called_once_with("parent_appointment_id")

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_batch_get_facility_names(self, mock_metadata) -> None:
        """Test batch fetching of facility names, skipping blank values."""
        from facility_recurring_scheduler.utils.constants import FIELD_FACILITY_KEY

        mock_event = MagicMock()

        mock_queryset = MagicMock()
        mock_queryset.values_list.return_value = [
            ("parent-1", "Downtown Clinic"),
            ("parent-2", "Uptown Clinic"),
            ("parent-3", ""),  # blank → excluded
        ]
        mock_metadata.objects.filter.return_value = mock_queryset

        extender = RecurrenceExtender(mock_event)
        result = extender._batch_get_facility_names(["parent-1", "parent-2", "parent-3"])

        assert result == {
            "parent-1": "Downtown Clinic",
            "parent-2": "Uptown Clinic",
        }
        mock_metadata.objects.filter.assert_called_once_with(
            appointment_id__in=["parent-1", "parent-2", "parent-3"],
            key=FIELD_FACILITY_KEY,
        )

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_batch_get_facility_names_handles_errors(self, mock_metadata) -> None:
        """A metadata read failure degrades to an empty map (cron must not abort)."""
        mock_event = MagicMock()
        mock_metadata.objects.filter.side_effect = Exception("db error")

        extender = RecurrenceExtender(mock_event)
        assert extender._batch_get_facility_names(["parent-1"]) == {}

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.Facility")
    def test_batch_get_facility_states(self, mock_facility) -> None:
        """Test batch fetching of facility state codes for a set of names."""
        mock_event = MagicMock()

        mock_queryset = MagicMock()
        mock_queryset.values_list.return_value = [
            ("Downtown Clinic", "NY"),
            ("Uptown Clinic", "CA"),
        ]
        mock_facility.objects.filter.return_value = mock_queryset

        extender = RecurrenceExtender(mock_event)
        result = extender._batch_get_facility_states(["Downtown Clinic", "Uptown Clinic"])

        assert result == {"Downtown Clinic": "NY", "Uptown Clinic": "CA"}

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.Facility")
    def test_batch_get_facility_states_skips_query_when_no_names(self, mock_facility) -> None:
        """No facility names → no Facility query is issued."""
        mock_event = MagicMock()

        extender = RecurrenceExtender(mock_event)
        result = extender._batch_get_facility_states([None, ""])

        assert result == {}
        mock_facility.objects.filter.assert_not_called()

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_get_active_recurring_parents_uses_select_related(
        self, mock_metadata, mock_appointment_model
    ) -> None:
        """Test that select_related is used for FK optimization."""
        mock_event = MagicMock()

        # Setup the metadata query
        mock_meta_queryset = MagicMock()
        mock_meta_queryset.exclude.return_value.values_list.return_value = ["parent-123"]
        mock_metadata.objects.filter.return_value = mock_meta_queryset

        # Setup parent query
        mock_parent_queryset = MagicMock()
        mock_exclude_result = MagicMock()
        mock_select_related = MagicMock()
        mock_select_related.__iter__ = lambda self: iter([])
        mock_exclude_result.select_related.return_value = mock_select_related
        mock_parent_queryset.exclude.return_value = mock_exclude_result
        mock_appointment_model.objects.filter.return_value = mock_parent_queryset

        extender = RecurrenceExtender(mock_event)
        extender._get_active_recurring_parents()

        # Verify select_related was called with the correct fields
        mock_exclude_result.select_related.assert_called_once_with(
            "note_type", "location", "provider", "patient"
        )

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.log")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentModel")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.AppointmentMetadata")
    def test_per_parent_error_handling_continues_on_failure(
        self, mock_metadata, mock_appointment_model, mock_schedule_event, mock_calc_date, mock_get_tz, mock_log
    ) -> None:
        """Test that one bad parent doesn't stop others from being processed."""
        mock_event = MagicMock()
        now = datetime.datetime.now(datetime.timezone.utc)

        # Create two parents - first will fail, second should succeed
        mock_bad_parent = MagicMock()
        mock_bad_parent.id = "bad-parent"
        mock_bad_parent.start_time = now - datetime.timedelta(days=30)

        mock_good_parent = MagicMock()
        mock_good_parent.id = "good-parent"
        mock_good_parent.start_time = now - datetime.timedelta(days=30)
        mock_good_parent.duration_minutes = 60
        mock_good_parent.location.id = "loc-1"
        mock_good_parent.provider.id = "prov-1"
        mock_good_parent.note_type.id = "note-type-1"
        mock_good_parent.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_good_parent.patient = None

        # Setup parent IDs query
        mock_parent_ids_queryset = MagicMock()
        mock_parent_ids_queryset.exclude.return_value.values_list.return_value = [
            "bad-parent", "good-parent"
        ]

        # Setup batch metadata query
        mock_recurrence_queryset = MagicMock()
        mock_recurrence_queryset.values_list.return_value = [
            ("bad-parent", "weekly"), ("good-parent", "weekly")
        ]

        # Setup batch children query
        latest_child_time = now + datetime.timedelta(days=60)
        mock_children_queryset = MagicMock()
        mock_exclude_children = MagicMock()
        mock_children_values = MagicMock()
        mock_children_values.annotate.return_value = [
            {"parent_appointment_id": "good-parent", "latest_start": latest_child_time}
        ]
        mock_exclude_children.values.return_value = mock_children_values
        mock_children_queryset.exclude.return_value = mock_exclude_children

        # Setup parent appointment query
        mock_parent_queryset = MagicMock()
        mock_select_related = MagicMock()
        mock_select_related.__iter__ = lambda self: iter([mock_bad_parent, mock_good_parent])
        mock_parent_queryset.exclude.return_value.select_related.return_value = mock_select_related

        def metadata_filter_side_effect(**kwargs):
            if "key" in kwargs and kwargs["key"] == FIELD_RECURRENCE_KEY:
                if "appointment_id__in" in kwargs:
                    return mock_recurrence_queryset
                else:
                    return mock_parent_ids_queryset
            return MagicMock()

        def appointment_filter_side_effect(**kwargs):
            if "id__in" in kwargs:
                return mock_parent_queryset
            if "parent_appointment_id__in" in kwargs:
                return mock_children_queryset
            return MagicMock()

        mock_metadata.objects.filter.side_effect = metadata_filter_side_effect
        mock_appointment_model.objects.filter.side_effect = appointment_filter_side_effect

        # Make bad parent's note_type access raise an exception
        type(mock_bad_parent).note_type = property(
            fget=lambda self: (_ for _ in ()).throw(Exception("Corrupt data"))
        )

        mock_get_tz.return_value = ZoneInfo("America/New_York")

        def calc_date_side_effect(start_time, count, recurrence, local_tz):
            return latest_child_time + datetime.timedelta(weeks=count)
        mock_calc_date.side_effect = calc_date_side_effect

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender.execute()

        # Should still have effects from the good parent
        assert len(effects) > 0
        # Should have logged an exception about the bad parent
        mock_log.exception.assert_called()

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.log")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    def test_infinite_loop_prevention_with_max_iterations(
        self, mock_schedule_event, mock_calc_date, mock_get_tz, mock_log
    ) -> None:
        """Test that max iterations cap prevents runaway loops."""
        from facility_recurring_scheduler.handlers.recurrence_extender import MAX_ITERATIONS

        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-1"
        mock_parent.patient = None

        now = datetime.datetime.now(datetime.timezone.utc)
        last_date = now + datetime.timedelta(days=1)
        # Set target very far in future to trigger max iterations
        target_date = now + datetime.timedelta(days=400)

        def side_effect(start_time, count, recurrence, local_tz):
            return last_date + datetime.timedelta(days=count)
        mock_calc_date.side_effect = side_effect

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, last_date, target_date, "daily", is_schedule_event=True
        )

        # Should cap at MAX_ITERATIONS
        assert len(effects) == MAX_ITERATIONS
        mock_log.warning.assert_called()

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.ScheduleEvent")
    def test_create_events_to_horizon_skips_past_dates(
        self, mock_schedule_event, mock_calc_date, mock_get_tz
    ) -> None:
        """Test that past dates are skipped when the latest active child is in the past.

        Exercises the helper directly: even when last_date is slightly in the
        past, only future occurrences (>= now) are created.
        """
        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"
        mock_parent.duration_minutes = 30
        mock_parent.location.id = "loc-1"
        mock_parent.provider.id = "prov-1"
        mock_parent.note_type.id = "note-1"
        mock_parent.patient = None

        now = datetime.datetime.now(datetime.timezone.utc)
        # Latest active child is slightly in the past
        last_date = now - datetime.timedelta(days=30)
        target_date = now + datetime.timedelta(days=TARGET_HORIZON_DAYS)

        def side_effect(start_time, count, recurrence, local_tz):
            return last_date + datetime.timedelta(weeks=count)
        mock_calc_date.side_effect = side_effect

        mock_effect = MagicMock()
        mock_schedule_event.return_value = mock_effect

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, last_date, target_date, "weekly", is_schedule_event=True
        )

        # All created events should be in the future — past weeks should be skipped
        created_times = [
            mock_schedule_event.call_args_list[i].kwargs["start_time"]
            for i in range(len(mock_schedule_event.call_args_list))
        ]
        for t in created_times:
            assert t >= now, f"Event created in the past: {t}"

        # Should still have some events (the ones from now to horizon)
        assert len(effects) > 0

    @patch("facility_recurring_scheduler.handlers.recurrence_extender.log")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.get_timezone_for_location")
    @patch("facility_recurring_scheduler.handlers.recurrence_extender.calculate_recurrence_date")
    def test_unknown_recurrence_returns_empty_in_horizon(
        self, mock_calc_date, mock_get_tz, mock_log
    ) -> None:
        """Test that unknown recurrence types in _create_events_to_horizon return empty."""
        mock_event = MagicMock()
        mock_get_tz.return_value = ZoneInfo("America/New_York")

        mock_parent = MagicMock()
        mock_parent.id = "parent-123"

        last_date = datetime.datetime(2024, 1, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
        target_date = datetime.datetime(2024, 4, 1, 14, 0, tzinfo=ZoneInfo("UTC"))

        mock_calc_date.side_effect = ValueError("Unknown recurrence type: 'biweekly'")

        extender = RecurrenceExtender(mock_event)
        effects = extender._create_events_to_horizon(
            mock_parent, last_date, target_date, "biweekly", is_schedule_event=True
        )

        assert effects == []
        mock_log.warning.assert_called()
