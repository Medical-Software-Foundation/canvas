"""Dropdown choices derived from the instance."""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.options import (
    build_options,
    list_appointment_types,
    list_locations,
    list_priorities,
    list_providers,
    time_window_by_value,
    windows_for_value,
)


def _queryset(items):
    """A queryset stand-in whose ``order_by`` returns the same items."""
    qs = MagicMock()
    qs.order_by.return_value = items
    return qs


def _note_type(dbid, code, name):
    note_type = MagicMock()
    note_type.dbid = dbid
    note_type.code = code
    note_type.name = name
    return note_type


class TestListAppointmentTypes:
    def test_only_bookable_types_are_requested(self):
        # A waitlist entry for something nobody can book is a dead row.
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset([])

            list_appointment_types(WaitlistConfig.from_secrets({}))

        assert note_type_model.objects.filter.call_args.kwargs == {
            "is_scheduleable": True,
            "is_active": True,
            "is_visible": True,
            "deprecated_at__isnull": True,
        }

    def test_unset_secret_returns_every_bookable_type(self):
        types = [_note_type(1, "estab", "Established"), _note_type(2, "newpt", "New Patient")]
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset(types)

            options = list_appointment_types(WaitlistConfig.from_secrets({}))

        assert [option["code"] for option in options] == ["estab", "newpt"]

    def test_configured_secret_narrows_the_list(self):
        types = [_note_type(1, "estab", "Established"), _note_type(2, "newpt", "New Patient")]
        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "newpt"})
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset(types)

            options = list_appointment_types(config)

        assert [option["code"] for option in options] == ["newpt"]

    def test_narrowing_ignores_case(self):
        types = [_note_type(1, "Estab", "Established")]
        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "estab"})
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset(types)

            options = list_appointment_types(config)

        assert len(options) == 1

    def test_type_without_a_name_falls_back_to_its_code(self):
        types = [_note_type(1, "estab", "")]
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset(types)

            options = list_appointment_types(WaitlistConfig.from_secrets({}))

        assert options[0]["name"] == "estab"

    def test_a_configured_list_matching_nothing_offers_everything_instead(self):
        # A typo in the variable is a mistake, not an instruction to offer
        # nothing. An empty dropdown teaches a scheduler nothing about why.
        types = [_note_type(1, "estab", "Established")]
        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "typo"})
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset(types)

            options = list_appointment_types(config)

        assert [option["code"] for option in options] == ["estab"]

    def test_falling_back_is_logged_as_an_error(self):
        import sys

        types = [_note_type(1, "estab", "Established")]
        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "typo"})
        sys.modules["logger"].log.error.reset_mock()
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset(types)

            list_appointment_types(config)

        assert sys.modules["logger"].log.error.called

    def test_an_instance_with_nothing_bookable_is_not_an_error(self):
        # Nothing to fall back to, so there is nothing to warn about either.
        import sys

        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "estab"})
        sys.modules["logger"].log.error.reset_mock()
        with patch("scheduling_waitlist.services.options.NoteType") as note_type_model:
            note_type_model.objects.filter.return_value = _queryset([])

            assert list_appointment_types(config) == []

        assert not sys.modules["logger"].log.error.called


class TestListProviders:
    def test_only_active_staff_are_requested(self):
        with patch("scheduling_waitlist.services.options.Staff") as staff_model:
            staff_model.objects.filter.return_value = _queryset([])

            list_providers()

        assert staff_model.objects.filter.call_args.kwargs == {"active": True}

    def test_provider_name_joins_first_and_last(self, mock_staff):
        with patch("scheduling_waitlist.services.options.Staff") as staff_model:
            staff_model.objects.filter.return_value = _queryset([mock_staff])

            options = list_providers()

        assert options[0]["name"] == "Alice Chen"

    def test_nameless_staff_get_a_readable_placeholder(self):
        staff = MagicMock()
        staff.dbid = 5
        staff.first_name = ""
        staff.last_name = ""
        with patch("scheduling_waitlist.services.options.Staff") as staff_model:
            staff_model.objects.filter.return_value = _queryset([staff])

            options = list_providers()

        # Never render a bare "None" into a dropdown.
        assert options[0]["name"] == "Unnamed staff member"


class TestListLocations:
    def test_only_active_locations_are_requested(self):
        with patch("scheduling_waitlist.services.options.PracticeLocation") as location_model:
            location_model.objects.filter.return_value = _queryset([])

            list_locations()

        assert location_model.objects.filter.call_args.kwargs == {"active": True}

    def test_prefers_the_full_name(self, mock_location):
        with patch("scheduling_waitlist.services.options.PracticeLocation") as location_model:
            location_model.objects.filter.return_value = _queryset([mock_location])

            options = list_locations()

        assert options[0]["name"] == "Riverside Clinic"

    def test_falls_back_to_the_short_name(self):
        location = MagicMock()
        location.dbid = 3
        location.full_name = ""
        location.short_name = "Riverside"
        with patch("scheduling_waitlist.services.options.PracticeLocation") as location_model:
            location_model.objects.filter.return_value = _queryset([location])

            options = list_locations()

        assert options[0]["name"] == "Riverside"


class TestListPriorities:
    def test_labels_carry_their_rank_in_configured_order(self):
        options = list_priorities(WaitlistConfig.from_secrets({}))

        assert options == [
            {"label": "High", "rank": 0},
            {"label": "Medium", "rank": 1},
            {"label": "Low", "rank": 2},
        ]


class TestTimeWindows:
    def test_any_time_is_offered_first(self):
        assert time_window_by_value("any")["label"] == "Any time"

    def test_unknown_window_is_not_invented(self):
        assert time_window_by_value("whenever") is None

    def test_any_time_stores_no_structured_window(self):
        # Nothing stored means nothing to filter on, which is what "any" means.
        assert windows_for_value("any") == []

    def test_unknown_window_stores_nothing(self):
        assert windows_for_value("nonsense") == []

    def test_weekday_mornings_stores_weekdays_and_a_time_range(self):
        assert windows_for_value("weekday_am") == [
            {"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"}
        ]

    def test_weekend_stores_saturday_and_sunday(self):
        assert windows_for_value("weekend")[0]["days"] == [5, 6]


class TestBuildOptions:
    def _patched(self, config):
        patches = {
            "NoteType": [_note_type(1, "estab", "Established")],
            "Staff": [],
            "PracticeLocation": [],
        }
        with (
            patch("scheduling_waitlist.services.options.NoteType") as note_type_model,
            patch("scheduling_waitlist.services.options.Staff") as staff_model,
            patch("scheduling_waitlist.services.options.PracticeLocation") as location_model,
        ):
            note_type_model.objects.filter.return_value = _queryset(patches["NoteType"])
            staff_model.objects.filter.return_value = _queryset(patches["Staff"])
            location_model.objects.filter.return_value = _queryset(patches["PracticeLocation"])
            return build_options(config)

    def test_payload_carries_every_list_the_form_needs(self):
        payload = self._patched(WaitlistConfig.from_secrets({}))

        assert set(payload) >= {
            "appointment_types",
            "providers",
            "locations",
            "priorities",
            "time_windows",
            "statuses",
        }

    def test_adding_is_possible_with_nothing_configured(self):
        # Configuration narrows the list; it is not a precondition for using the
        # plugin at all.
        payload = self._patched(WaitlistConfig.from_secrets({}))

        assert payload["can_add"] is True

    def test_adding_is_possible_with_a_configured_list(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "estab"})

        assert self._patched(config)["can_add"] is True

    def test_adding_is_impossible_only_when_the_instance_has_nothing_bookable(self):
        with (
            patch("scheduling_waitlist.services.options.NoteType") as note_type_model,
            patch("scheduling_waitlist.services.options.Staff") as staff_model,
            patch("scheduling_waitlist.services.options.PracticeLocation") as location_model,
        ):
            note_type_model.objects.filter.return_value = _queryset([])
            staff_model.objects.filter.return_value = _queryset([])
            location_model.objects.filter.return_value = _queryset([])
            payload = build_options(WaitlistConfig.from_secrets({}))

        assert payload["can_add"] is False

    def test_status_vocabulary_matches_the_entry_lifecycle(self):
        payload = self._patched(WaitlistConfig.from_secrets({}))

        assert [status["value"] for status in payload["statuses"]] == [
            "waiting",
            "offered",
            "scheduled",
            "removed",
            "expired",
        ]
