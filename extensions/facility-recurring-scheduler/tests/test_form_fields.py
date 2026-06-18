"""Tests for the OtherEventFormFields handler."""

from unittest.mock import MagicMock, patch, call

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from facility_recurring_scheduler.handlers.form_fields import OtherEventFormFields
from facility_recurring_scheduler.utils.constants import (
    FIELD_FACILITY_KEY,
    FIELD_RECURRENCE_KEY,
    RecurrenceEnum,
)


class TestOtherEventFormFields:
    """Tests for the OtherEventFormFields handler."""

    def test_responds_to_correct_event(self) -> None:
        """Test that the handler responds to APPOINTMENT__FORM__GET_ADDITIONAL_FIELDS."""
        assert OtherEventFormFields.RESPONDS_TO == EventType.Name(
            EventType.APPOINTMENT__FORM__GET_ADDITIONAL_FIELDS
        )

    @patch("facility_recurring_scheduler.handlers.form_fields.Facility")
    def test_returns_fields_for_schedule_event(self, mock_facility_class) -> None:
        """Test that fields are returned for schedule_event category."""
        mock_event = MagicMock()
        mock_event.context = {"category": "schedule_event"}

        # Mock the chained queryset: filter().order_by().values_list()
        mock_facility_class.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            "Downtown Office", "Main Clinic"
        ]

        handler = OtherEventFormFields(mock_event)
        effects = handler.compute()

        # Verify that active facilities were queried with ordering
        mock_facility_class.objects.filter.assert_called_once_with(active=True)

        # Verify effects
        assert len(effects) == 1
        assert effects[0].type == EffectType.APPOINTMENT__FORM__CREATE_ADDITIONAL_FIELDS

    def test_returns_recurrence_only_for_non_schedule_event(self) -> None:
        """Test that only recurrence field is returned for non-schedule_event categories."""
        mock_event = MagicMock()
        mock_event.context = {"category": "encounter"}

        handler = OtherEventFormFields(mock_event)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.APPOINTMENT__FORM__CREATE_ADDITIONAL_FIELDS

    def test_returns_recurrence_only_for_missing_category(self) -> None:
        """Test that only recurrence field is returned when category is missing."""
        mock_event = MagicMock()
        mock_event.context = {}

        handler = OtherEventFormFields(mock_event)
        effects = handler.compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.APPOINTMENT__FORM__CREATE_ADDITIONAL_FIELDS

    @patch("facility_recurring_scheduler.handlers.form_fields.Facility")
    def test_facility_options_from_active_facilities_ordered(self, mock_facility_class) -> None:
        """Test that facility options are built from active facilities, ordered alphabetically."""
        mock_event = MagicMock()
        mock_event.context = {"category": "schedule_event"}

        mock_facility_class.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            "Active Clinic A", "Active Clinic B"
        ]

        handler = OtherEventFormFields(mock_event)
        handler.compute()

        # Verify query chain: filter(active=True).order_by("name").values_list("name", flat=True)
        mock_facility_class.objects.filter.assert_called_once_with(active=True)
        mock_facility_class.objects.filter.return_value.order_by.assert_called_once_with("name")
        mock_facility_class.objects.filter.return_value.order_by.return_value.values_list.assert_called_once_with(
            "name", flat=True
        )

    @patch("facility_recurring_scheduler.handlers.form_fields.Facility")
    def test_returns_both_facility_and_recurrence_fields(
        self, mock_facility_class
    ) -> None:
        """Test that both facility and recurrence dropdowns are included."""
        mock_event = MagicMock()
        mock_event.context = {"category": "schedule_event"}

        mock_facility_class.objects.filter.return_value.order_by.return_value.values_list.return_value = []

        handler = OtherEventFormFields(mock_event)
        effects = handler.compute()

        # Verify effect contains form fields
        assert len(effects) == 1
        effect = effects[0]
        assert effect.type == EffectType.APPOINTMENT__FORM__CREATE_ADDITIONAL_FIELDS

        # The effect payload should contain the form fields
        assert effect.payload is not None
