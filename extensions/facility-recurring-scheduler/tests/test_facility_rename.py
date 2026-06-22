"""Tests for the FacilityRename handler."""

from unittest.mock import MagicMock, patch, call

import pytest
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.note import NoteTypeCategories

from facility_recurring_scheduler.handlers.facility_rename import FacilityRename
from facility_recurring_scheduler.utils.constants import FIELD_FACILITY_KEY


class TestFacilityRename:
    """Tests for the FacilityRename handler."""

    def test_responds_to_correct_event(self) -> None:
        """Test that the handler responds to APPOINTMENT_CREATED."""
        assert FacilityRename.RESPONDS_TO == EventType.Name(
            EventType.APPOINTMENT_CREATED
        )

    @patch("facility_recurring_scheduler.handlers.facility_rename.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentModel")
    def test_renames_parent_event_when_facility_selected(
        self, mock_appointment_model, mock_metadata, mock_schedule_event
    ) -> None:
        """Test that description is updated when facility is selected for parent event."""
        mock_event = MagicMock()
        mock_event.target.id = "appt-123"

        # Mock appointment as schedule event (parent - no parent_appointment_id)
        mock_appointment = MagicMock()
        mock_appointment.id = "appt-123"
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        # Mock facility metadata exists
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "Downtown Clinic"
        )

        # Mock ScheduleEvent effect
        mock_effect_instance = MagicMock()
        mock_schedule_event.return_value = mock_effect_instance

        handler = FacilityRename(mock_event)
        effects = handler.compute()

        # Verify mocks
        assert mock_appointment_model.mock_calls == [
            call.objects.select_related("note_type"),
            call.objects.select_related().get(id="appt-123"),
        ]
        assert mock_metadata.mock_calls == [
            call.objects.filter(appointment=mock_appointment, key=FIELD_FACILITY_KEY),
            call.objects.filter().values_list("value", flat=True),
            call.objects.filter().values_list().first(),
        ]
        assert mock_schedule_event.mock_calls == [
            call(instance_id="appt-123"),
            call().update(),
        ]

        # Verify effect
        assert len(effects) == 1
        assert mock_effect_instance.description == "Downtown Clinic"

    @patch("facility_recurring_scheduler.handlers.facility_rename.ScheduleEvent")
    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentModel")
    def test_renames_child_event_using_parent_facility(
        self, mock_appointment_model, mock_metadata, mock_schedule_event
    ) -> None:
        """Test that child events get facility name from parent's metadata."""
        mock_event = MagicMock()
        mock_event.target.id = "child-appt-123"

        # Mock appointment as child schedule event (has parent_appointment_id)
        mock_appointment = MagicMock()
        mock_appointment.id = "child-appt-123"
        mock_appointment.parent_appointment_id = "parent-appt-456"
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        # Mock facility metadata from parent
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "Parent Facility"
        )

        # Mock ScheduleEvent effect
        mock_effect_instance = MagicMock()
        mock_schedule_event.return_value = mock_effect_instance

        handler = FacilityRename(mock_event)
        effects = handler.compute()

        # Verify parent metadata was queried
        assert mock_metadata.mock_calls == [
            call.objects.filter(appointment_id="parent-appt-456", key=FIELD_FACILITY_KEY),
            call.objects.filter().values_list("value", flat=True),
            call.objects.filter().values_list().first(),
        ]

        # Verify effect
        assert len(effects) == 1
        assert mock_effect_instance.description == "Parent Facility"

    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentMetadata")
    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentModel")
    def test_skips_when_no_facility_selected(
        self, mock_appointment_model, mock_metadata
    ) -> None:
        """Test that no update occurs when no facility is selected."""
        mock_event = MagicMock()
        mock_event.target.id = "appt-123"

        mock_appointment = MagicMock()
        mock_appointment.parent_appointment_id = None
        mock_appointment.note_type.category = NoteTypeCategories.SCHEDULE_EVENT
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        # No facility metadata
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = None

        handler = FacilityRename(mock_event)
        effects = handler.compute()

        # Verify appointment was fetched
        mock_appointment_model.objects.select_related.return_value.get.assert_called_once_with(id="appt-123")

        # Verify no effects
        assert effects == []

    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentModel")
    def test_skips_non_schedule_events(self, mock_appointment_model) -> None:
        """Test that handler skips regular appointments."""
        mock_event = MagicMock()
        mock_event.target.id = "appt-123"

        mock_appointment = MagicMock()
        mock_appointment.note_type.category = "encounter"  # Not a schedule event
        mock_appointment_model.objects.select_related.return_value.get.return_value = mock_appointment

        handler = FacilityRename(mock_event)
        effects = handler.compute()

        # Verify mocks
        assert mock_appointment_model.mock_calls == [
            call.objects.select_related("note_type"),
            call.objects.select_related().get(id="appt-123"),
        ]

        # Verify no effects
        assert effects == []

    @patch("facility_recurring_scheduler.handlers.facility_rename.log")
    @patch("facility_recurring_scheduler.handlers.facility_rename.AppointmentModel")
    def test_does_not_exist_handled_gracefully(
        self, mock_appointment_model, mock_log
    ) -> None:
        """Test that DoesNotExist is handled when appointment is missing."""
        mock_event = MagicMock()
        mock_event.target.id = "missing-123"

        mock_appointment_model.DoesNotExist = Exception
        mock_appointment_model.objects.select_related.return_value.get.side_effect = Exception("not found")

        handler = FacilityRename(mock_event)
        effects = handler.compute()

        assert effects == []
        mock_log.warning.assert_called()
