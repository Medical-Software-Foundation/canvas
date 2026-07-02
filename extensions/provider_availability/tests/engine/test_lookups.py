"""Tests for provider_availability.engine.lookups."""

from unittest.mock import MagicMock, call, patch

from provider_availability.engine.lookups import (
    get_active_locations,
    get_active_providers,
    get_active_staff_ids,
    get_scheduleable_visit_types,
)


LOOKUPS_MODULE = "provider_availability.engine.lookups"


class TestGetActiveStaffIds:
    def test_returns_all_active_staff_ids(self):
        s1 = MagicMock()
        s1.id = "staff-1"
        s2 = MagicMock()
        s2.id = "staff-2"

        with patch(f"{LOOKUPS_MODULE}.Staff.objects") as mock_objects:
            mock_objects.filter.return_value = [s1, s2]

            result = get_active_staff_ids()

            assert mock_objects.mock_calls == [call.filter(active=True)]
            assert result == {"staff-1", "staff-2"}

    def test_empty(self):
        with patch(f"{LOOKUPS_MODULE}.Staff.objects") as mock_objects:
            mock_objects.filter.return_value = []

            assert get_active_staff_ids() == set()


class TestGetActiveProviders:
    def test_returns_sorted_providers(self):
        staff_b = MagicMock()
        staff_b.id = "s2"
        staff_b.first_name = "Jane"
        staff_b.last_name = "Zebra"
        staff_b.npi_number = "222"

        staff_a = MagicMock()
        staff_a.id = "s1"
        staff_a.first_name = "John"
        staff_a.last_name = "Alpha"
        staff_a.npi_number = "111"

        with patch(f"{LOOKUPS_MODULE}.Staff.objects") as mock_objects:
            mock_objects.filter.return_value.distinct.return_value = [staff_b, staff_a]

            result = get_active_providers()

            assert mock_objects.mock_calls == [
                call.filter(active=True, roles__role_type="PROVIDER"),
                call.filter().distinct(),
            ]
            # Sorted by last_name
            assert result[0]["name"] == "John Alpha"
            assert result[1]["name"] == "Jane Zebra"

    def test_empty(self):
        with patch(f"{LOOKUPS_MODULE}.Staff.objects") as mock_objects:
            mock_objects.filter.return_value.distinct.return_value = []

            result = get_active_providers()

            assert result == []


class TestGetActiveLocations:
    def test_returns_sorted_locations(self):
        loc_b = MagicMock()
        loc_b.id = "l2"
        loc_b.full_name = "West Office"
        loc_b.short_name = "West"

        loc_a = MagicMock()
        loc_a.id = "l1"
        loc_a.full_name = "East Office"
        loc_a.short_name = "East"

        with patch(f"{LOOKUPS_MODULE}.PracticeLocation.objects") as mock_objects:
            mock_objects.filter.return_value = [loc_b, loc_a]

            result = get_active_locations()

            assert mock_objects.mock_calls == [call.filter(active=True)]
            assert result[0]["name"] == "East Office"
            assert result[1]["name"] == "West Office"

    def test_uses_short_name_fallback(self):
        loc = MagicMock()
        loc.id = "l1"
        loc.full_name = ""
        loc.short_name = "Main"

        with patch(f"{LOOKUPS_MODULE}.PracticeLocation.objects") as mock_objects:
            mock_objects.filter.return_value = [loc]

            result = get_active_locations()

            assert result[0]["name"] == "Main"


class TestGetScheduleableVisitTypes:
    def test_returns_deduplicated_sorted_types(self):
        nt1 = MagicMock()
        nt1.id = "vt1"
        nt1.name = "Telehealth"

        nt2 = MagicMock()
        nt2.id = "vt2"
        nt2.name = "In-Person"

        nt_dup = MagicMock()
        nt_dup.id = "vt1"  # Duplicate of nt1
        nt_dup.name = "Telehealth"

        with patch(f"{LOOKUPS_MODULE}.NoteType.objects") as mock_objects:
            mock_objects.filter.side_effect = [
                [nt1, nt2],  # scheduleable
                [nt_dup],    # schedule_event (duplicate)
            ]

            result = get_scheduleable_visit_types()

            # Deduplicated + sorted
            assert len(result) == 2
            assert result[0]["name"] == "In-Person"
            assert result[1]["name"] == "Telehealth"

    def test_schedule_event_adds_unique_types(self):
        nt1 = MagicMock()
        nt1.id = "vt1"
        nt1.name = "Telehealth"

        nt_event = MagicMock()
        nt_event.id = "vt3"
        nt_event.name = "Follow-Up"

        with patch(f"{LOOKUPS_MODULE}.NoteType.objects") as mock_objects:
            mock_objects.filter.side_effect = [
                [nt1],       # scheduleable
                [nt_event],  # schedule_event (unique)
            ]

            result = get_scheduleable_visit_types()

            assert len(result) == 2
            assert result[0]["name"] == "Follow-Up"
            assert result[1]["name"] == "Telehealth"

    def test_empty(self):
        with patch(f"{LOOKUPS_MODULE}.NoteType.objects") as mock_objects:
            mock_objects.filter.side_effect = [[], []]

            result = get_scheduleable_visit_types()

            assert result == []
