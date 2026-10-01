"""Tests for display-timezone resolution and date formatting.

No canvas_sdk methods are mocked. Staff records come from the real
StaffFactory; the API instance uses a real FakeRequest with proper headers.
"""

import arrow
import pytest

from canvas_sdk.test_utils.factories import StaffFactory

from tests._helpers import build_api


@pytest.mark.django_db
class TestDisplayTimezone:
    def test_staff_tz_preferred(self) -> None:
        staff = StaffFactory.create(last_known_timezone="America/New_York")
        api = build_api(headers={"canvas-logged-in-user-id": str(staff.id)})
        assert api._display_tz() == "America/New_York"

    def test_falls_back_to_secret_when_staff_tz_missing(self) -> None:
        staff = StaffFactory.create(last_known_timezone=None)
        api = build_api(
            secrets={"INSTANCE_TIMEZONE": "America/Los_Angeles"},
            headers={"canvas-logged-in-user-id": str(staff.id)},
        )
        assert api._display_tz() == "America/Los_Angeles"

    def test_falls_back_to_utc_when_no_staff_and_no_secret(self) -> None:
        # No staff_id header, no secret → UTC default.
        api = build_api()
        assert api._display_tz() == "UTC"

    def test_unknown_staff_id_falls_back_to_secret_then_utc(self) -> None:
        api = build_api(
            secrets={"INSTANCE_TIMEZONE": "Europe/Belgrade"},
            headers={"canvas-logged-in-user-id": "00000000-0000-0000-0000-000000000000"},
        )
        assert api._display_tz() == "Europe/Belgrade"

    def test_secret_whitespace_stripped(self) -> None:
        api = build_api(secrets={"INSTANCE_TIMEZONE": "  Asia/Tokyo  "})
        assert api._display_tz() == "Asia/Tokyo"

    def test_memoized_per_instance(self) -> None:
        staff = StaffFactory.create(last_known_timezone="Asia/Tokyo")
        api = build_api(headers={"canvas-logged-in-user-id": str(staff.id)})
        first = api._display_tz()
        # Update underlying record — memoized value should not change.
        staff.last_known_timezone = "Europe/London"
        staff.save()
        assert api._display_tz() == first


@pytest.mark.django_db
class TestFormatLocal:
    def test_edt_late_night_keeps_local_date(self) -> None:
        staff = StaffFactory.create(last_known_timezone="America/New_York")
        api = build_api(headers={"canvas-logged-in-user-id": str(staff.id)})
        # 2026-04-15 21:44 EDT == 2026-04-16 01:44 UTC
        utc_dt = arrow.get("2026-04-16T01:44:00+00:00")
        assert api._format_local(utc_dt, "MM.DD.YYYY") == "04.15.2026"

    def test_utc_when_no_tz_resolved(self) -> None:
        api = build_api()
        utc_dt = arrow.get("2026-04-16T01:44:00+00:00")
        assert api._format_local(utc_dt, "MM.DD.YYYY") == "04.16.2026"
