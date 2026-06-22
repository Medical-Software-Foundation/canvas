"""Tests for the timezone_helper utility module."""

from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from facility_recurring_scheduler.utils.timezone_helper import (
    get_timezone_from_state,
    get_timezone_for_appointment,
    get_timezone_for_location,
    STATE_TO_TIMEZONE,
)
from facility_recurring_scheduler.utils.constants import DEFAULT_TIMEZONE


class TestGetTimezoneFromState:
    """Tests for get_timezone_from_state function."""

    def test_returns_eastern_timezone_for_ny(self) -> None:
        """Test that NY returns Eastern timezone."""
        result = get_timezone_from_state("NY")
        assert result == ZoneInfo("America/New_York")

    def test_returns_central_timezone_for_il(self) -> None:
        """Test that IL returns Central timezone."""
        result = get_timezone_from_state("IL")
        assert result == ZoneInfo("America/Chicago")

    def test_returns_mountain_timezone_for_co(self) -> None:
        """Test that CO returns Mountain timezone."""
        result = get_timezone_from_state("CO")
        assert result == ZoneInfo("America/Denver")

    def test_returns_pacific_timezone_for_ca(self) -> None:
        """Test that CA returns Pacific timezone."""
        result = get_timezone_from_state("CA")
        assert result == ZoneInfo("America/Los_Angeles")

    def test_returns_alaska_timezone_for_ak(self) -> None:
        """Test that AK returns Alaska timezone."""
        result = get_timezone_from_state("AK")
        assert result == ZoneInfo("America/Anchorage")

    def test_returns_hawaii_timezone_for_hi(self) -> None:
        """Test that HI returns Hawaii timezone."""
        result = get_timezone_from_state("HI")
        assert result == ZoneInfo("Pacific/Honolulu")

    def test_handles_lowercase_state_code(self) -> None:
        """Test that lowercase state codes are handled correctly."""
        result = get_timezone_from_state("ny")
        assert result == ZoneInfo("America/New_York")

    def test_returns_none_for_invalid_state(self) -> None:
        """Test that invalid state code returns None."""
        result = get_timezone_from_state("XX")
        assert result is None

    def test_returns_none_for_empty_state(self) -> None:
        """Test that empty state code returns None."""
        result = get_timezone_from_state("")
        assert result is None

    def test_returns_none_for_none_state(self) -> None:
        """Test that None state code returns None."""
        result = get_timezone_from_state(None)
        assert result is None

    def test_arizona_no_dst(self) -> None:
        """Test that Arizona returns Phoenix timezone (no DST)."""
        result = get_timezone_from_state("AZ")
        assert result == ZoneInfo("America/Phoenix")

    def test_puerto_rico_territory(self) -> None:
        """Test that PR returns Puerto Rico timezone."""
        result = get_timezone_from_state("PR")
        assert result == ZoneInfo("America/Puerto_Rico")


class TestGetTimezoneForAppointment:
    """Tests for get_timezone_for_appointment function."""

    @patch("facility_recurring_scheduler.utils.timezone_helper.Facility")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_returns_facility_timezone_when_available(
        self, mock_metadata, mock_facility_class
    ) -> None:
        """Test that facility timezone is used when facility is selected."""
        mock_appointment = MagicMock()

        # Mock facility metadata exists
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "Test Facility"
        )

        # Mock facility with state
        mock_facility = MagicMock()
        mock_facility.state_code = "CA"
        mock_facility_class.objects.filter.return_value.first.return_value = mock_facility

        result = get_timezone_for_appointment(mock_appointment)

        assert result == ZoneInfo("America/Los_Angeles")

    @patch("facility_recurring_scheduler.utils.timezone_helper.Patient")
    @patch("facility_recurring_scheduler.utils.timezone_helper.Facility")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_returns_patient_preferred_timezone_when_no_facility(
        self, mock_metadata, mock_facility_class, mock_patient_class
    ) -> None:
        """Test that patient's last_known_timezone is used when no facility."""
        mock_appointment = MagicMock()

        # No facility metadata
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = None

        # Mock patient with last_known_timezone
        mock_patient = MagicMock()
        mock_patient.last_known_timezone = "America/Denver"
        mock_patient_class.objects.filter.return_value.first.return_value = mock_patient

        result = get_timezone_for_appointment(mock_appointment, patient_id="patient-123")

        assert result == ZoneInfo("America/Denver")

    @patch("facility_recurring_scheduler.utils.timezone_helper.Patient")
    @patch("facility_recurring_scheduler.utils.timezone_helper.Facility")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_returns_patient_address_timezone_when_no_preferred(
        self, mock_metadata, mock_facility_class, mock_patient_class
    ) -> None:
        """Test that patient's address timezone is used when no preferred timezone."""
        mock_appointment = MagicMock()

        # No facility metadata
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = None

        # Mock patient with address but no last_known_timezone
        mock_patient = MagicMock()
        mock_patient.last_known_timezone = None

        mock_address = MagicMock()
        mock_address.state_code = "TX"
        mock_patient.addresses.all.return_value = [mock_address]

        mock_patient_class.objects.filter.return_value.first.return_value = mock_patient

        result = get_timezone_for_appointment(mock_appointment, patient_id="patient-123")

        assert result == ZoneInfo("America/Chicago")

    @patch("facility_recurring_scheduler.utils.timezone_helper.Patient")
    @patch("facility_recurring_scheduler.utils.timezone_helper.Facility")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_returns_default_timezone_when_no_other_source(
        self, mock_metadata, mock_facility_class, mock_patient_class
    ) -> None:
        """Test that default timezone is used when no other source."""
        mock_appointment = MagicMock()

        # No facility metadata
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = None

        # No patient
        mock_patient_class.objects.filter.return_value.first.return_value = None

        result = get_timezone_for_appointment(mock_appointment)

        assert result == ZoneInfo(DEFAULT_TIMEZONE)

    @patch("facility_recurring_scheduler.utils.timezone_helper.log")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_handles_metadata_exception_gracefully(self, mock_metadata, mock_log) -> None:
        """Test that exceptions in metadata lookup are handled gracefully and logged."""
        mock_appointment = MagicMock()

        # Metadata lookup raises exception
        mock_metadata.objects.filter.side_effect = Exception("Database error")

        result = get_timezone_for_appointment(mock_appointment)

        # Should fall back to default
        assert result == ZoneInfo(DEFAULT_TIMEZONE)
        # Should log a warning
        mock_log.warning.assert_called()

    @patch("facility_recurring_scheduler.utils.timezone_helper.Facility")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_handles_facility_without_state_code(
        self, mock_metadata, mock_facility_class
    ) -> None:
        """Test handling when facility exists but has no state code."""
        mock_appointment = MagicMock()

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "Test Facility"
        )

        mock_facility = MagicMock()
        mock_facility.state_code = None
        mock_facility_class.objects.filter.return_value.first.return_value = mock_facility

        result = get_timezone_for_appointment(mock_appointment)

        # Should fall back to default
        assert result == ZoneInfo(DEFAULT_TIMEZONE)


class TestGetTimezoneForLocation:
    """Tests for get_timezone_for_location function."""

    @patch("facility_recurring_scheduler.utils.timezone_helper.Facility")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_resolves_facility_timezone_from_metadata(
        self, mock_metadata, mock_facility_class
    ) -> None:
        """Facility selected in metadata resolves via its state when not prefetched."""
        mock_appointment = MagicMock()
        mock_appointment.patient = None

        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = (
            "Test Facility"
        )
        mock_facility = MagicMock()
        mock_facility.state_code = "CA"
        mock_facility_class.objects.filter.return_value.first.return_value = mock_facility

        result = get_timezone_for_location(mock_appointment)

        assert result == ZoneInfo("America/Los_Angeles")

    @patch("facility_recurring_scheduler.utils.timezone_helper.Patient")
    @patch("facility_recurring_scheduler.utils.timezone_helper.Facility")
    @patch("facility_recurring_scheduler.utils.timezone_helper.AppointmentMetadata")
    def test_reuses_loaded_patient_without_requery(
        self, mock_metadata, mock_facility_class, mock_patient_class
    ) -> None:
        """Patient is read from the appointment, never re-queried by id."""
        mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = None

        mock_patient = MagicMock()
        mock_patient.last_known_timezone = "America/Denver"
        mock_appointment = MagicMock()
        mock_appointment.patient = mock_patient

        result = get_timezone_for_location(mock_appointment)

        assert result == ZoneInfo("America/Denver")
        # The loaded patient is used directly — no Patient.objects lookup
        mock_patient_class.objects.filter.assert_not_called()

    def test_uses_prefetched_facility_data_without_queries(self) -> None:
        """Prefetched facility_name + state map resolve with no DB access."""
        mock_appointment = MagicMock()
        mock_appointment.patient = None

        result = get_timezone_for_location(
            mock_appointment,
            facility_name="Downtown Clinic",
            facility_state_by_name={"Downtown Clinic": "NY"},
        )

        assert result == ZoneInfo("America/New_York")

    def test_falls_back_to_default_with_prefetched_empties(self) -> None:
        """No facility and no patient → default timezone, no queries."""
        mock_appointment = MagicMock()
        mock_appointment.patient = None

        result = get_timezone_for_location(
            mock_appointment, facility_name=None, facility_state_by_name={}
        )

        assert result == ZoneInfo(DEFAULT_TIMEZONE)

    @patch("facility_recurring_scheduler.utils.timezone_helper.log")
    def test_handles_exception_when_accessing_patient(self, mock_log) -> None:
        """Test handling when accessing patient raises exception and logs warning."""
        mock_appointment = MagicMock()

        # Make patient access raise exception
        type(mock_appointment).patient = property(fget=lambda self: (_ for _ in ()).throw(
            Exception("Patient access error")
        ))

        result = get_timezone_for_location(
            mock_appointment, facility_name=None, facility_state_by_name={}
        )

        # Should still fall back to default and log a warning
        assert result == ZoneInfo(DEFAULT_TIMEZONE)
        mock_log.warning.assert_called()


class TestStateToTimezoneMapping:
    """Tests for the STATE_TO_TIMEZONE mapping."""

    def test_all_50_states_covered(self) -> None:
        """Test that all 50 US states are covered."""
        us_states = {
            "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
            "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
            "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
            "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
            "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
        }
        assert us_states.issubset(set(STATE_TO_TIMEZONE.keys()))

    def test_dc_covered(self) -> None:
        """Test that Washington DC is covered."""
        assert "DC" in STATE_TO_TIMEZONE

    def test_territories_covered(self) -> None:
        """Test that US territories are covered."""
        territories = {"AS", "GU", "MP", "PR", "VI"}
        assert territories.issubset(set(STATE_TO_TIMEZONE.keys()))
