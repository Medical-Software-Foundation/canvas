from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff

from open_availability.protocols.open_availability import (
    DEFAULT_SCHEDULABLE_ROLES,
    DEFAULT_START_TIME,
    DEFAULT_END_TIME,
    DEFAULT_TIMEZONE,
    OpenAvailabilityOnActivation,
    OpenAvailabilityOnDeactivation,
    create_availability_event,
    get_availability_times,
    get_availability_timezone,
    get_calendar_description,
    get_schedulable_roles,
    is_staff_schedulable,
    parse_time,
)


class TestEventTypeConfiguration:
    """Tests that handler classes respond to the correct event types."""

    def test_activation_responds_to_staff_activated(self) -> None:
        assert OpenAvailabilityOnActivation.RESPONDS_TO == EventType.Name(
            EventType.STAFF_ACTIVATED
        )

    def test_deactivation_responds_to_staff_deactivated(self) -> None:
        assert OpenAvailabilityOnDeactivation.RESPONDS_TO == EventType.Name(
            EventType.STAFF_DEACTIVATED
        )



class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_schedulable_roles_from_secret(self) -> None:
        """Test parsing roles from secrets."""
        secrets = {"SCHEDULABLE_ROLES": "MD,DO,NP"}
        result = get_schedulable_roles(secrets)
        assert result == {"MD", "DO", "NP"}

    def test_get_schedulable_roles_default(self) -> None:
        """Test default roles when secret not set."""
        secrets: dict[str, str] = {}
        result = get_schedulable_roles(secrets)
        expected = {r.strip() for r in DEFAULT_SCHEDULABLE_ROLES.split(",")}
        assert result == expected

    def test_get_schedulable_roles_with_whitespace(self) -> None:
        """Test roles are trimmed and uppercased."""
        secrets = {"SCHEDULABLE_ROLES": " md , do , np "}
        result = get_schedulable_roles(secrets)
        assert result == {"MD", "DO", "NP"}

    def test_get_schedulable_roles_empty_string(self) -> None:
        """Test empty string returns empty set."""
        secrets = {"SCHEDULABLE_ROLES": ""}
        result = get_schedulable_roles(secrets)
        assert result == set()

    def test_is_staff_schedulable_with_matching_role(self) -> None:
        """Test staff with matching role is schedulable."""
        mock_staff = MagicMock()
        mock_staff.top_role_abbreviation = "MD"
        mock_staff.last_known_timezone = "America/Chicago"
        schedulable_roles = {"MD", "DO", "NP", "PA"}

        result = is_staff_schedulable(mock_staff, schedulable_roles)

        assert result is True

    def test_is_staff_schedulable_with_non_matching_role(self) -> None:
        """Test staff with non-matching role is not schedulable."""
        mock_staff = MagicMock()
        mock_staff.top_role_abbreviation = "ADMIN"
        schedulable_roles = {"MD", "DO", "NP", "PA"}

        result = is_staff_schedulable(mock_staff, schedulable_roles)

        assert result is False

    def test_is_staff_schedulable_with_no_role(self) -> None:
        """Test staff without role is not schedulable."""
        mock_staff = MagicMock()
        mock_staff.top_role_abbreviation = None
        schedulable_roles = {"MD", "DO", "NP", "PA"}

        result = is_staff_schedulable(mock_staff, schedulable_roles)

        assert result is False

    def test_is_staff_schedulable_case_insensitive(self) -> None:
        """Test role matching is case insensitive."""
        mock_staff = MagicMock()
        mock_staff.top_role_abbreviation = "md"  # lowercase
        schedulable_roles = {"MD", "DO"}

        result = is_staff_schedulable(mock_staff, schedulable_roles)

        assert result is True

    def test_get_calendar_description(self) -> None:
        """Test calendar description generation."""
        result = get_calendar_description("jsmith")
        assert result == "jsmith"


class TestParseTime:
    """Tests for the parse_time helper."""

    def test_valid_time(self) -> None:
        assert parse_time("08:00") == (8, 0)

    def test_valid_time_with_whitespace(self) -> None:
        assert parse_time("  14:30  ") == (14, 30)

    def test_invalid_format_no_colon(self) -> None:
        with pytest.raises(ValueError):
            parse_time("0800")

    def test_invalid_hour_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            parse_time("25:00")

    def test_invalid_minute_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            parse_time("08:60")

    def test_midnight(self) -> None:
        assert parse_time("00:00") == (0, 0)

    def test_end_of_day(self) -> None:
        assert parse_time("23:59") == (23, 59)


class TestGetAvailabilityTimezone:
    """Tests for the get_availability_timezone helper."""

    def test_valid_timezone_chicago(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "America/Chicago"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("America/Chicago")

    def test_valid_timezone_los_angeles(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "America/Los_Angeles"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("America/Los_Angeles")

    def test_valid_timezone_denver(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "America/Denver"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("America/Denver")

    def test_valid_timezone_new_york(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "America/New_York"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("America/New_York")

    def test_valid_timezone_anchorage(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "America/Anchorage"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("America/Anchorage")

    def test_valid_timezone_honolulu(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "Pacific/Honolulu"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("Pacific/Honolulu")

    def test_valid_timezone_utc(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "UTC"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("UTC")

    def test_any_valid_iana_timezone_accepted(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "America/Phoenix"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("America/Phoenix")

    def test_invalid_timezone_falls_back(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "Invalid/Zone"}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo(DEFAULT_TIMEZONE)

    def test_missing_timezone_uses_default(self) -> None:
        result = get_availability_timezone({})
        assert result == ZoneInfo(DEFAULT_TIMEZONE)

    def test_whitespace_stripped(self) -> None:
        secrets = {"AVAILABILITY_TIMEZONE": "  America/Los_Angeles  "}
        result = get_availability_timezone(secrets)
        assert result == ZoneInfo("America/Los_Angeles")


class TestGetAvailabilityTimes:
    """Tests for get_availability_times parsing secrets."""

    def test_all_valid(self) -> None:
        secrets = {
            "AVAILABILITY_START_TIME": "09:00",
            "AVAILABILITY_END_TIME": "17:00",
            "AVAILABILITY_TIMEZONE": "America/Chicago",
        }
        start, end, tz = get_availability_times(secrets)
        assert start == (9, 0)
        assert end == (17, 0)
        assert tz == ZoneInfo("America/Chicago")

    def test_defaults_when_empty(self) -> None:
        start, end, tz = get_availability_times({})
        assert start == parse_time(DEFAULT_START_TIME)
        assert end == parse_time(DEFAULT_END_TIME)
        assert tz == ZoneInfo(DEFAULT_TIMEZONE)

    def test_invalid_start_falls_back(self) -> None:
        secrets = {"AVAILABILITY_START_TIME": "bad"}
        start, end, tz = get_availability_times(secrets)
        assert start == parse_time(DEFAULT_START_TIME)

    def test_invalid_end_falls_back(self) -> None:
        secrets = {"AVAILABILITY_END_TIME": "bad"}
        start, end, tz = get_availability_times(secrets)
        assert end == parse_time(DEFAULT_END_TIME)


class TestCreateAvailabilityEvent:
    """Tests for create_availability_event with timezone-aware secrets."""

    def test_converts_eastern_daylight_to_utc(self) -> None:
        """During EDT (summer), America/New_York is UTC-4."""
        secrets = {
            "AVAILABILITY_START_TIME": "08:00",
            "AVAILABILITY_END_TIME": "20:00",
            "AVAILABILITY_TIMEZONE": "America/New_York",
        }
        # June 15 is during EDT
        frozen_now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ):
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", secrets)

                    kwargs = mock_event_class.call_args[1]
                    # EDT is UTC-4, so 08:00 EDT = 12:00 UTC
                    assert kwargs["starts_at"].hour == 12
                    assert kwargs["starts_at"].minute == 0
                    # 20:00 EDT = 00:00 UTC next day
                    assert kwargs["ends_at"].hour == 0
                    assert kwargs["ends_at"].minute == 0

    def test_converts_eastern_standard_to_utc(self) -> None:
        """During EST (winter), America/New_York is UTC-5."""
        secrets = {
            "AVAILABILITY_START_TIME": "08:00",
            "AVAILABILITY_END_TIME": "20:00",
            "AVAILABILITY_TIMEZONE": "America/New_York",
        }
        # January is during EST
        frozen_now = datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ):
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", secrets)

                    kwargs = mock_event_class.call_args[1]
                    # EST is UTC-5, so 08:00 EST = 13:00 UTC
                    assert kwargs["starts_at"].hour == 13
                    assert kwargs["starts_at"].minute == 0
                    # 20:00 EST = 01:00 UTC next day
                    assert kwargs["ends_at"].hour == 1
                    assert kwargs["ends_at"].minute == 0

    def test_recurrence_is_daily(self) -> None:
        """Verify recurrence is daily with interval 1."""
        secrets = {
            "AVAILABILITY_START_TIME": "08:00",
            "AVAILABILITY_END_TIME": "20:00",
            "AVAILABILITY_TIMEZONE": "America/New_York",
        }
        frozen_now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ) as mock_recurrence:
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", secrets)

                    kwargs = mock_event_class.call_args[1]
                    assert kwargs["recurrence_frequency"] == mock_recurrence.Daily
                    assert kwargs["recurrence_interval"] == 1

    def test_recurrence_ends_25_years_later(self) -> None:
        """Verify recurrence ends 25 years from now."""
        secrets = {
            "AVAILABILITY_START_TIME": "08:00",
            "AVAILABILITY_END_TIME": "20:00",
            "AVAILABILITY_TIMEZONE": "America/New_York",
        }
        frozen_now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ):
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", secrets)

                    kwargs = mock_event_class.call_args[1]
                    assert kwargs["recurrence_ends_at"].year == 2051

    def test_event_title_is_available(self) -> None:
        """Verify event title is 'Available'."""
        secrets = {
            "AVAILABILITY_START_TIME": "08:00",
            "AVAILABILITY_END_TIME": "20:00",
            "AVAILABILITY_TIMEZONE": "America/New_York",
        }
        frozen_now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ):
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", secrets)

                    kwargs = mock_event_class.call_args[1]
                    assert kwargs["title"] == "Available"
                    assert kwargs["calendar_id"] == "cal-123"

    def test_end_before_start_wraps_to_next_day(self) -> None:
        """When end time is before start time, it should wrap to the next day."""
        secrets = {
            "AVAILABILITY_START_TIME": "20:00",
            "AVAILABILITY_END_TIME": "06:00",
            "AVAILABILITY_TIMEZONE": "UTC",
        }
        frozen_now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ):
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", secrets)

                    kwargs = mock_event_class.call_args[1]
                    assert kwargs["starts_at"] == datetime(
                        2026, 6, 15, 20, 0, tzinfo=timezone.utc
                    )
                    assert kwargs["ends_at"] == datetime(
                        2026, 6, 16, 6, 0, tzinfo=timezone.utc
                    )

    def test_defaults_when_secrets_empty(self) -> None:
        """Verify defaults are used when secrets are empty."""
        frozen_now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ):
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", {})

                    kwargs = mock_event_class.call_args[1]
                    # Default: 08:00-20:00 America/New_York
                    # EDT is UTC-4, so 08:00 EDT = 12:00 UTC
                    assert kwargs["starts_at"].hour == 12
                    assert kwargs["ends_at"].hour == 0

    def test_leap_year_recurrence_end_falls_back(self) -> None:
        """Verify Feb 29 falls back to Feb 28 when target year isn't a leap year."""
        secrets = {
            "AVAILABILITY_START_TIME": "08:00",
            "AVAILABILITY_END_TIME": "20:00",
            "AVAILABILITY_TIMEZONE": "UTC",
        }
        frozen_now = datetime(2028, 2, 29, 14, 30, 0, tzinfo=timezone.utc)
        with patch(
            "open_availability.protocols.open_availability.datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.return_value = frozen_now
            with patch(
                "open_availability.protocols.open_availability.Event"
            ) as mock_event_class:
                with patch(
                    "open_availability.protocols.open_availability.EventRecurrence"
                ):
                    mock_instance = MagicMock()
                    mock_instance.create.return_value = MagicMock()
                    mock_event_class.return_value = mock_instance

                    create_availability_event("cal-123", secrets)

                    kwargs = mock_event_class.call_args[1]
                    # 2028 + 25 = 2053, not a leap year
                    assert kwargs["recurrence_ends_at"].year == 2053
                    assert kwargs["recurrence_ends_at"].month == 2
                    assert kwargs["recurrence_ends_at"].day == 28


class TestDeactivationDatetimeValues:
    """Tests that deactivation sets recurrence_ends_at to 'now'."""

    def test_deactivation_sets_recurrence_ends_at_to_now(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Verify deactivation handler sets recurrence_ends_at to current time."""
        frozen_now = datetime(2026, 7, 20, 15, 45, 0, tzinfo=timezone.utc)

        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"

        mock_calendar = MagicMock()
        mock_existing_event = MagicMock()
        mock_existing_event.id = "event-456"
        mock_existing_event.title = "Available"
        mock_existing_event.starts_at = datetime(
            2026, 1, 1, 8, 0, tzinfo=timezone.utc
        )
        mock_existing_event.ends_at = datetime(
            2026, 1, 2, 3, 59, tzinfo=timezone.utc
        )
        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_existing_event])
        mock_calendar.events.filter.return_value = mock_queryset

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                with patch(
                    "open_availability.protocols.open_availability.Event"
                ) as mock_event_class:
                    with patch(
                        "open_availability.protocols.open_availability.datetime"
                    ) as mock_dt:
                        mock_dt.now.return_value = frozen_now
                        mock_dt.side_effect = lambda *a, **kw: datetime(
                            *a, **kw
                        )
                        mock_staff_objects.get.return_value = mock_staff
                        mock_calendar_objects.get.return_value = mock_calendar

                        mock_update_effect = MagicMock()
                        mock_event_instance = MagicMock()
                        mock_event_instance.update.return_value = (
                            mock_update_effect
                        )
                        mock_event_class.return_value = mock_event_instance

                        handler = OpenAvailabilityOnDeactivation(
                            event=mock_event
                        )
                        handler.secrets = mock_secrets

                        effects = handler.compute()

                        kwargs = mock_event_class.call_args[1]
                        assert kwargs["recurrence_ends_at"] == frozen_now
                        assert len(effects) == 1


class TestOpenAvailabilityOnActivation:
    """Tests for the activation handler."""

    def test_creates_calendar_and_event_for_eligible_staff(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test calendar and event are created for eligible staff."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"
        mock_staff.last_known_timezone = "America/Chicago"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                with patch(
                    "open_availability.protocols.open_availability.Calendar"
                ) as mock_calendar_class:
                    with patch(
                        "open_availability.protocols.open_availability.Event"
                    ) as mock_event_class:
                        with patch(
                            "open_availability.protocols.open_availability.uuid4"
                        ) as mock_uuid:
                            with patch(
                                "open_availability.protocols.open_availability.CalendarType"
                            ):
                                with patch(
                                    "open_availability.protocols.open_availability.EventRecurrence"
                                ):
                                    from uuid import UUID

                                    mock_staff_objects.get.return_value = mock_staff
                                    mock_calendar_objects.filter.return_value.first.return_value = None
                                    mock_uuid.return_value = UUID(
                                        "12345678-1234-5678-1234-567812345678"
                                    )

                                    mock_calendar_effect = MagicMock()
                                    mock_calendar_instance = MagicMock()
                                    mock_calendar_instance.create.return_value = (
                                        mock_calendar_effect
                                    )
                                    mock_calendar_class.return_value = mock_calendar_instance

                                    mock_event_effect = MagicMock()
                                    mock_event_instance = MagicMock()
                                    mock_event_instance.create.return_value = mock_event_effect
                                    mock_event_class.return_value = mock_event_instance

                                    handler = OpenAvailabilityOnActivation(event=mock_event)
                                    handler.secrets = mock_secrets

                                    effects = handler.compute()

                                    # Verify Staff.objects was called
                                    assert mock_staff_objects.mock_calls == [
                                        call.get(id="staff-123")
                                    ]

                                    # Verify uuid4 was called
                                    assert mock_uuid.mock_calls == [call()]

                                    # Verify Calendar was created with correct params
                                    assert mock_calendar_class.called
                                    calendar_call_kwargs = mock_calendar_class.call_args[1]
                                    assert calendar_call_kwargs["provider"] == "staff-123"
                                    assert (
                                        calendar_call_kwargs["description"]
                                        == "jsmith"
                                    )

                                    # Verify Event was created
                                    assert mock_event_class.called
                                    event_call_kwargs = mock_event_class.call_args[1]
                                    assert event_call_kwargs["title"] == "Available"

                                    # Verify effects returned
                                    assert len(effects) == 2
                                    assert effects[0] == mock_calendar_effect
                                    assert effects[1] == mock_event_effect

    def test_uses_existing_calendar_when_found(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test uses existing calendar instead of creating new one."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"

        mock_existing_calendar = MagicMock()
        mock_existing_calendar.id = "existing-cal-id"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                with patch(
                    "open_availability.protocols.open_availability.Calendar"
                ) as mock_calendar_class:
                    with patch(
                        "open_availability.protocols.open_availability.Event"
                    ) as mock_event_class:
                        with patch(
                            "open_availability.protocols.open_availability.EventRecurrence"
                        ):
                            mock_staff_objects.get.return_value = mock_staff
                            mock_calendar_objects.filter.return_value.first.return_value = (
                                mock_existing_calendar
                            )

                            mock_event_effect = MagicMock()
                            mock_event_instance = MagicMock()
                            mock_event_instance.create.return_value = mock_event_effect
                            mock_event_class.return_value = mock_event_instance

                            handler = OpenAvailabilityOnActivation(event=mock_event)
                            handler.secrets = mock_secrets

                            effects = handler.compute()

                            # Verify Staff.objects was called
                            assert mock_staff_objects.mock_calls == [
                                call.get(id="staff-123")
                            ]

                            # Verify CalendarModel.objects.filter was called
                            assert call.filter(description="jsmith") in (
                                mock_calendar_objects.mock_calls
                            )

                            # Verify Calendar.create was NOT called
                            assert not mock_calendar_class.called

                            # Verify Event was created with existing calendar ID
                            assert mock_event_class.called
                            event_call_kwargs = mock_event_class.call_args[1]
                            assert event_call_kwargs["calendar_id"] == "existing-cal-id"

                            # Only event effect returned (no calendar effect)
                            assert len(effects) == 1
                            assert effects[0] == mock_event_effect

    def test_no_effects_for_non_schedulable_staff(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test no effects for staff with non-schedulable role."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-789"

        mock_staff = MagicMock()
        mock_staff.id = "staff-789"
        mock_staff.full_name = "Admin User"
        mock_staff.top_role_abbreviation = "ADMIN"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            mock_staff_objects.get.return_value = mock_staff

            handler = OpenAvailabilityOnActivation(event=mock_event)
            handler.secrets = mock_secrets

            effects = handler.compute()

            assert mock_staff_objects.mock_calls == [call.get(id="staff-789")]
            assert effects == []

    def test_no_effects_for_staff_without_role(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test no effects for staff without a role."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-456"

        mock_staff = MagicMock()
        mock_staff.id = "staff-456"
        mock_staff.full_name = "John Doe"
        mock_staff.top_role_abbreviation = None

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            mock_staff_objects.get.return_value = mock_staff

            handler = OpenAvailabilityOnActivation(event=mock_event)
            handler.secrets = mock_secrets

            effects = handler.compute()

            assert mock_staff_objects.mock_calls == [call.get(id="staff-456")]
            assert effects == []

    def test_no_effects_for_staff_not_found(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test no effects when staff not found."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            mock_staff_objects.get.side_effect = Staff.DoesNotExist

            handler = OpenAvailabilityOnActivation(event=mock_event)
            handler.secrets = mock_secrets

            effects = handler.compute()

            assert mock_staff_objects.mock_calls == [call.get(id="staff-123")]
            assert effects == []

    def test_uses_default_roles_when_secret_not_set(
        self, mock_secrets_empty: dict[str, str]
    ) -> None:
        """Test default roles are used when secret not configured."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"
        mock_staff.last_known_timezone = "America/Chicago"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                with patch(
                    "open_availability.protocols.open_availability.Calendar"
                ) as mock_calendar_class:
                    with patch(
                        "open_availability.protocols.open_availability.Event"
                    ) as mock_event_class:
                        with patch(
                            "open_availability.protocols.open_availability.uuid4"
                        ) as mock_uuid:
                            with patch(
                                "open_availability.protocols.open_availability.CalendarType"
                            ):
                                with patch(
                                    "open_availability.protocols.open_availability.EventRecurrence"
                                ):
                                    from uuid import UUID

                                    mock_staff_objects.get.return_value = mock_staff
                                    mock_calendar_objects.filter.return_value.first.return_value = None
                                    mock_uuid.return_value = UUID(
                                        "12345678-1234-5678-1234-567812345678"
                                    )

                                    mock_calendar_effect = MagicMock()
                                    mock_calendar_instance = MagicMock()
                                    mock_calendar_instance.create.return_value = (
                                        mock_calendar_effect
                                    )
                                    mock_calendar_class.return_value = mock_calendar_instance

                                    mock_event_effect = MagicMock()
                                    mock_event_instance = MagicMock()
                                    mock_event_instance.create.return_value = mock_event_effect
                                    mock_event_class.return_value = mock_event_instance

                                    handler = OpenAvailabilityOnActivation(event=mock_event)
                                    handler.secrets = mock_secrets_empty

                                    effects = handler.compute()

                                    # MD should still be in default roles
                                    assert len(effects) == 2
                                    assert mock_staff_objects.mock_calls == [
                                        call.get(id="staff-123")
                                    ]


class TestOpenAvailabilityOnDeactivation:
    """Tests for the deactivation handler."""

    def test_updates_event_for_eligible_staff(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test event recurrence end date is updated on deactivation."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"
        mock_staff.last_known_timezone = "America/Chicago"

        mock_calendar = MagicMock()
        mock_calendar.id = "calendar-123"
        mock_calendar.description = "jsmith"

        mock_calendar_event = MagicMock()
        mock_calendar_event.id = "event-123"
        mock_calendar_event.title = "Available"

        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_calendar_event])
        mock_calendar.events.filter.return_value = mock_queryset

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                with patch(
                    "open_availability.protocols.open_availability.Event"
                ) as mock_event_class:
                    mock_staff_objects.get.return_value = mock_staff
                    mock_calendar_objects.get.return_value = mock_calendar

                    mock_update_effect = MagicMock()
                    mock_event_instance = MagicMock()
                    mock_event_instance.update.return_value = mock_update_effect
                    mock_event_class.return_value = mock_event_instance

                    handler = OpenAvailabilityOnDeactivation(event=mock_event)
                    handler.secrets = mock_secrets

                    effects = handler.compute()

                    # Verify Staff.objects
                    assert mock_staff_objects.mock_calls == [
                        call.get(id="staff-123")
                    ]

                    # Verify CalendarModel.objects was called (allow chained calls)
                    assert call.get(description="jsmith") in (
                        mock_calendar_objects.mock_calls
                    )

                    # Verify calendar.events.filter was called with title and active recurrence
                    mock_calendar.events.filter.assert_called_once()
                    filter_kwargs = mock_calendar.events.filter.call_args[1]
                    assert filter_kwargs["title"] == "Available"
                    assert "recurrence_ends_at__gt" in filter_kwargs

                    # Verify Event was created with event_id and update called
                    assert mock_event_class.called
                    assert mock_event_instance.update.called

                    # Verify effect returned
                    assert len(effects) == 1
                    assert effects[0] == mock_update_effect

    def test_ends_all_stacked_events_on_deactivation(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test deactivation ends ALL active events, not just one."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"

        mock_calendar = MagicMock()

        mock_event_1 = MagicMock()
        mock_event_1.id = "event-1"
        mock_event_1.title = "Available"
        mock_event_2 = MagicMock()
        mock_event_2.id = "event-2"
        mock_event_2.title = "Available"

        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_event_1, mock_event_2])
        mock_calendar.events.filter.return_value = mock_queryset

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                with patch(
                    "open_availability.protocols.open_availability.Event"
                ) as mock_event_class:
                    mock_staff_objects.get.return_value = mock_staff
                    mock_calendar_objects.get.return_value = mock_calendar

                    mock_update_effect = MagicMock()
                    mock_event_instance = MagicMock()
                    mock_event_instance.update.return_value = mock_update_effect
                    mock_event_class.return_value = mock_event_instance

                    handler = OpenAvailabilityOnDeactivation(event=mock_event)
                    handler.secrets = mock_secrets

                    effects = handler.compute()

                    # Both events should be ended
                    assert len(effects) == 2
                    assert mock_event_class.call_count == 2

    def test_no_effects_for_non_schedulable_staff(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test no effects for staff with non-schedulable role on deactivation."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-789"

        mock_staff = MagicMock()
        mock_staff.id = "staff-789"
        mock_staff.full_name = "Admin User"
        mock_staff.top_role_abbreviation = "ADMIN"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            mock_staff_objects.get.return_value = mock_staff

            handler = OpenAvailabilityOnDeactivation(event=mock_event)
            handler.secrets = mock_secrets

            effects = handler.compute()

            assert mock_staff_objects.mock_calls == [call.get(id="staff-789")]
            assert effects == []

    def test_no_effects_when_staff_not_found(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test no effects when staff not found on deactivation."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            mock_staff_objects.get.side_effect = Staff.DoesNotExist

            handler = OpenAvailabilityOnDeactivation(event=mock_event)
            handler.secrets = mock_secrets

            effects = handler.compute()

            assert mock_staff_objects.mock_calls == [call.get(id="staff-123")]
            assert effects == []

    def test_no_effects_when_calendar_not_found(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test no effects when calendar not found (staff created before plugin)."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"
        mock_staff.last_known_timezone = "America/Chicago"

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                mock_staff_objects.get.return_value = mock_staff
                mock_calendar_objects.get.side_effect = CalendarModel.DoesNotExist

                handler = OpenAvailabilityOnDeactivation(event=mock_event)
                handler.secrets = mock_secrets

                effects = handler.compute()

                assert mock_staff_objects.mock_calls == [
                    call.get(id="staff-123")
                ]
                assert mock_calendar_objects.mock_calls == [
                    call.get(description="jsmith")
                ]
                assert effects == []

    def test_no_effects_when_event_not_found(
        self, mock_secrets: dict[str, str]
    ) -> None:
        """Test no effects when availability event not found on calendar."""
        mock_event = MagicMock()
        mock_event.target.id = "staff-123"

        mock_staff = MagicMock()
        mock_staff.id = "jsmith"
        mock_staff.full_name = "Dr. Jane Smith"
        mock_staff.top_role_abbreviation = "MD"
        mock_staff.last_known_timezone = "America/Chicago"

        mock_calendar = MagicMock()
        mock_empty_queryset = MagicMock()
        mock_empty_queryset.exists.return_value = False
        mock_calendar.events.filter.return_value = mock_empty_queryset

        with patch(
            "open_availability.protocols.open_availability.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.protocols.open_availability.CalendarModel.objects"
            ) as mock_calendar_objects:
                mock_staff_objects.get.return_value = mock_staff
                mock_calendar_objects.get.return_value = mock_calendar

                handler = OpenAvailabilityOnDeactivation(event=mock_event)
                handler.secrets = mock_secrets

                effects = handler.compute()

                assert mock_staff_objects.mock_calls == [call.get(id="staff-123")]
                # Verify CalendarModel.objects was called (allow chained calls)
                assert call.get(description="jsmith") in (
                    mock_calendar_objects.mock_calls
                )
                # Verify filter was called with title and active recurrence
                mock_calendar.events.filter.assert_called_once()
                filter_kwargs = mock_calendar.events.filter.call_args[1]
                assert filter_kwargs["title"] == "Available"
                assert "recurrence_ends_at__gt" in filter_kwargs
                assert effects == []
