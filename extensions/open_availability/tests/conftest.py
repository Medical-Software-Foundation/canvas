import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event() -> MagicMock:
    """Create a base mock event."""
    event = MagicMock()
    event.target.id = "staff-123"
    return event


@pytest.fixture
def mock_staff() -> MagicMock:
    """Create a mock staff member with MD role."""
    staff = MagicMock()
    staff.id = "jsmith"
    staff.full_name = "Dr. Jane Smith"
    staff.top_role_abbreviation = "MD"
    staff.last_known_timezone = "America/Chicago"
    return staff


@pytest.fixture
def mock_staff_no_role() -> MagicMock:
    """Create a mock staff member without a role."""
    staff = MagicMock()
    staff.id = "jdoe"
    staff.full_name = "John Doe"
    staff.top_role_abbreviation = None
    return staff


@pytest.fixture
def mock_staff_non_schedulable() -> MagicMock:
    """Create a mock staff member with non-schedulable role."""
    staff = MagicMock()
    staff.id = "adminuser"
    staff.full_name = "Admin User"
    staff.top_role_abbreviation = "ADMIN"
    return staff


@pytest.fixture
def mock_secrets() -> dict[str, str]:
    """Create mock secrets with default schedulable roles and availability settings."""
    return {
        "SCHEDULABLE_ROLES": "MD,DO,NP,PA",
        "AVAILABILITY_START_TIME": "08:00",
        "AVAILABILITY_END_TIME": "20:00",
        "AVAILABILITY_TIMEZONE": "America/New_York",
    }


@pytest.fixture
def mock_secrets_empty() -> dict[str, str]:
    """Create empty mock secrets (uses defaults)."""
    return {}


@pytest.fixture
def mock_calendar() -> MagicMock:
    """Create a mock calendar."""
    calendar = MagicMock()
    calendar.id = "calendar-123"
    calendar.description = "jsmith"
    return calendar


@pytest.fixture
def mock_calendar_event() -> MagicMock:
    """Create a mock calendar event."""
    event = MagicMock()
    event.id = "event-123"
    event.title = "Available"
    return event
