"""Tests for provider_availability.engine.admin_calendar."""

from unittest.mock import MagicMock, call, patch

from provider_availability.engine.admin_calendar import (
    deterministic_calendar_id,
    get_admin_calendar_id,
    get_admin_calendars,
)


AC_MODULE = "provider_availability.engine.admin_calendar"


class TestDeterministicCalendarId:
    def test_stable_for_same_inputs(self):
        a = deterministic_calendar_id("p1", "admin", "loc-1")
        b = deterministic_calendar_id("p1", "admin", "loc-1")
        assert a == b  # deterministic -> racing creates collide instead of forking

    def test_differs_by_provider_type_and_location(self):
        base = deterministic_calendar_id("p1", "admin", None)
        assert base != deterministic_calendar_id("p2", "admin", None)
        assert base != deterministic_calendar_id("p1", "clinic", None)
        assert base != deterministic_calendar_id("p1", "admin", "loc-1")

    def test_is_a_uuid_string(self):
        import uuid as _uuid

        _uuid.UUID(deterministic_calendar_id("p1", "clinic", None))  # raises if not a valid UUID


def _lookup(mock_cal_objects, by_id=None, titled=()):
    """Calendar lookups: filter(id=...).first() for the fixed id, filter(title=...) for the name."""
    def fake_filter(*args, **kwargs):
        if "title" in kwargs:
            return list(titled)
        result = MagicMock()
        result.first.return_value = by_id
        return result
    mock_cal_objects.filter.side_effect = fake_filter


class TestGetAdminCalendarId:
    def test_existing_calendar(self):
        mock_cal = MagicMock()
        mock_cal.id = "cal-uuid-123"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("Jane", "Doe")
            mock_cal.description = "p1"  # tagged with this provider's staff key
            _lookup(mock_cal_objects, titled=[mock_cal])

            cal_id, effects = get_admin_calendar_id("p1")

            assert mock_staff_objects.mock_calls == [
                call.filter(id="p1"),
                call.filter().values_list("first_name", "last_name"),
                call.filter().values_list().first(),
            ]
            assert cal_id == str(mock_cal.id)
            assert effects == []

    def test_creates_new_calendar(self):
        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{AC_MODULE}.deterministic_calendar_id", return_value="new-cal-id"):
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("Jane", "Doe")
            mock_cal_objects.filter.return_value.first.return_value = None

            cal_id, effects = get_admin_calendar_id("p1")

            assert cal_id == "new-cal-id"
            assert len(effects) == 1

    def test_reuses_calendar_by_anchor_id(self):
        """A calendar matching the deterministic anchor id is reused without a title lookup."""
        mock_cal = MagicMock()
        mock_cal.id = "anchor-uuid"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("Jane", "Doe")
            mock_cal_objects.filter.return_value.first.return_value = mock_cal

            cal_id, effects = get_admin_calendar_id("p1")

            assert cal_id == "anchor-uuid"
            assert effects == []
            assert mock_cal_objects.filter.call_count == 1  # the fixed id only, no name lookup

    def test_existing_calendar_with_location(self):
        mock_loc = MagicMock()
        mock_loc.full_name = "Main Office"

        mock_cal = MagicMock()
        mock_cal.id = "cal-uuid-loc"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.PracticeLocation.objects") as mock_loc_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("Jane", "Doe")
            mock_loc_objects.get.return_value = mock_loc
            mock_cal.description = "p1"  # tagged with this provider's staff key
            _lookup(mock_cal_objects, titled=[mock_cal])

            cal_id, effects = get_admin_calendar_id("p1", "loc-1")

            assert cal_id == str(mock_cal.id)
            assert effects == []
            assert mock_cal_objects.filter.call_args.kwargs == {"title": "Jane Doe: Admin: Main Office"}

    def test_creates_new_calendar_with_location(self):
        mock_loc = MagicMock()
        mock_loc.full_name = "Main Office"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.PracticeLocation.objects") as mock_loc_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{AC_MODULE}.deterministic_calendar_id", return_value="new-cal-loc"):
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("Jane", "Doe")
            mock_loc_objects.get.return_value = mock_loc
            mock_cal_objects.filter.return_value.first.return_value = None

            cal_id, effects = get_admin_calendar_id("p1", "loc-1")

            assert cal_id == "new-cal-loc"
            assert len(effects) == 1

    def test_staff_not_found(self):
        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = None

            cal_id, effects = get_admin_calendar_id("p1")

            assert cal_id == ""
            assert effects == []

    def test_empty_provider_name(self):
        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("", "")

            cal_id, effects = get_admin_calendar_id("p1")

            assert cal_id == ""
            assert effects == []


class TestGetAdminCalendars:
    def test_returns_calendars(self):
        mock_cal = MagicMock()

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("Jane", "Doe")
            mock_cal_objects.filter.return_value = [mock_cal]

            result = get_admin_calendars("p1")

            assert len(result) == 1

    def test_staff_not_found(self):
        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = None

            result = get_admin_calendars("p1")

            assert result == []

    def test_empty_provider_name(self):
        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.filter.return_value.values_list.return_value.first.return_value = ("", "")

            result = get_admin_calendars("p1")

            assert result == []


class TestMissingClinicCalendarEffects:
    def _staff(self, key, name):
        s = MagicMock()
        s.id = key
        s.full_name = name
        return s

    def test_one_query_and_only_missing_staff_get_a_calendar(self):
        from provider_availability.engine.admin_calendar import (
            deterministic_calendar_id,
            missing_clinic_calendar_effects,
        )

        by_id = self._staff("k1", "Ann A")
        by_title = self._staff("k2", "Bea B")
        by_description = self._staff("k3", "Renamed C")
        missing = self._staff("k4", "Dee D")
        rows = [
            (deterministic_calendar_id("k1", "Clinic", None), "Old Name: Clinic", ""),
            ("legacy-2", "Bea B: Clinic", ""),
            ("legacy-3", "Cee C: Clinic", "k3"),
            ("admin-4", "Dee D: Administrative", "k4"),  # an Admin calendar is not a Clinic one
        ]
        with patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal:
            mock_cal.filter.return_value.values_list.return_value = rows
            effects = missing_clinic_calendar_effects([by_id, by_title, by_description, missing])

        assert mock_cal.filter.call_count == 1
        assert len(effects) == 1
        assert '"description": "k4"' in effects[0].payload
        assert deterministic_calendar_id("k4", "Clinic", None) in effects[0].payload

    def test_no_staff_no_query(self):
        from provider_availability.engine.admin_calendar import missing_clinic_calendar_effects

        with patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal:
            assert missing_clinic_calendar_effects([]) == []
        assert mock_cal.mock_calls == []


class TestCalendarOwnershipWithSharedNames:
    """Three staff profiles named Charles Brown (one per licensing state) must each
    get their own calendars, and saving one must not touch the others'."""

    def _cal(self, cal_id, description):
        c = MagicMock()
        c.id = cal_id
        c.description = description
        return c

    def test_tagged_calendar_is_used_even_with_a_shared_name(self):
        from provider_availability.engine.admin_calendar import find_own_calendar

        other = self._cal("cal-other", "key-b")
        mine = self._cal("cal-mine", "key-a")
        with patch(f"{AC_MODULE}.CalendarModel.objects") as objs, \
             patch(f"{AC_MODULE}.name_is_shared", return_value=True):
            _lookup(objs, titled=[other, mine])
            assert find_own_calendar("key-a", "Charles Brown", "Clinic", "Cool Clinic", "fixed") is mine

    def test_untagged_calendar_is_not_reused_when_the_name_is_shared(self):
        from provider_availability.engine.admin_calendar import find_own_calendar

        shared = self._cal("cal-legacy", "")
        with patch(f"{AC_MODULE}.CalendarModel.objects") as objs, \
             patch(f"{AC_MODULE}.name_is_shared", return_value=True):
            _lookup(objs, titled=[shared])
            assert find_own_calendar("key-a", "Charles Brown", "Clinic", "Cool Clinic", "fixed") is None

    def test_untagged_calendar_is_reused_for_a_unique_name(self):
        from provider_availability.engine.admin_calendar import find_own_calendar

        legacy = self._cal("cal-legacy", "")
        with patch(f"{AC_MODULE}.CalendarModel.objects") as objs, \
             patch(f"{AC_MODULE}.name_is_shared", return_value=False):
            _lookup(objs, titled=[legacy])
            assert find_own_calendar("key-a", "Jane Doe", "Clinic", None, "fixed") is legacy

    def test_another_profiles_calendar_is_never_reused(self):
        from provider_availability.engine.admin_calendar import find_own_calendar

        other = self._cal("cal-other", "key-b")
        with patch(f"{AC_MODULE}.CalendarModel.objects") as objs, \
             patch(f"{AC_MODULE}.name_is_shared", return_value=True):
            _lookup(objs, titled=[other])
            assert find_own_calendar("key-a", "Charles Brown", "Clinic", None, "fixed") is None

    def test_clearing_leaves_out_calendars_tagged_for_another_profile(self):
        from provider_availability.engine.admin_calendar import own_calendars_q

        q = str(own_calendars_q("key-a", "Charles Brown", "Clinic"))
        assert "('title__startswith', 'Charles Brown: Clinic')" in q
        assert "('description', 'key-a')" in q
        assert "key-b" not in q
        assert "('description', '')" in q  # untagged legacy calendars with the name

    def test_name_is_shared(self):
        from provider_availability.engine.admin_calendar import name_is_shared

        with patch(f"{AC_MODULE}.Staff.objects") as staff:
            staff.filter.return_value.values_list.return_value.first.return_value = ("Charles", "Brown")
            staff.filter.return_value.exclude.return_value.exists.return_value = True
            assert name_is_shared("key-a") is True
            staff.filter.return_value.exclude.return_value.exists.return_value = False
            assert name_is_shared("key-a") is False
