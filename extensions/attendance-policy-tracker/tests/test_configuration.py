"""Configuration storage, the text boundary, and who may change policy.

Policy reaches the plugin as text, from a store on an instance and from a
dictionary here, so these tests exercise the coercion in both directions and the
gate that decides who may write it.
"""

from typing import Any

import pytest

from attendance_policy_tracker.composition import (
    EDITABLE_SETTINGS,
    build,
    config_from,
    to_raw,
)
from attendance_policy_tracker.core.access import AccessList
from attendance_policy_tracker.core.config import DEFAULTS, ConfigError
from attendance_policy_tracker.core.contracts import CLINIC, PATIENT, STORE_METHODS, validate
from attendance_policy_tracker.core.view_preference import (
    SHOW_NON_COUNTING,
    set_show_non_counting,
    show_non_counting,
    truthy,
)


class FakeStore:
    """A settings store backed by a dictionary."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(values or {})

    def read(self) -> dict[str, str]:
        return dict(self.values)

    def write(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            if f"{value}".strip():
                self.values[key] = f"{value}".strip()
            else:
                self.values.pop(key, None)


class TestAccessList:
    """The one setting that stays in Canvas administration."""

    def test_empty_permits_nobody(self) -> None:
        access = AccessList("")
        assert access.is_empty()
        assert not access.permits("a" * 32)

    def test_none_permits_nobody(self) -> None:
        assert not AccessList(None).permits("a" * 32)

    def test_whitespace_separated(self) -> None:
        access = AccessList("aaa\nbbb  ccc")
        assert access.permits("aaa")
        assert access.permits("bbb")
        assert access.permits("ccc")
        assert not access.permits("ddd")

    def test_commas_also_separate(self) -> None:
        access = AccessList("aaa, bbb,ccc")
        assert access.permits("bbb")
        assert access.permits("ccc")

    def test_case_insensitive(self) -> None:
        assert AccessList("AbCdEf").permits("abcdef")

    def test_blank_key_never_permitted(self) -> None:
        """An absent session header must not match an entry."""
        access = AccessList("aaa")
        assert not access.permits("")
        assert not access.permits("   ")


class TestStoredPolicy:
    """Reading policy out of stored text."""

    def test_nothing_stored_gives_the_shipped_defaults(self) -> None:
        config = config_from({})
        assert config.warning_line == DEFAULTS["warning_line"]
        assert config.discharge_review_line == DEFAULTS["discharge_review_line"]
        assert config.default_attribution == PATIENT

    def test_numbers_arrive_as_text(self) -> None:
        config = config_from({"warning_line": "2", "discharge_review_line": "6"})
        assert config.warning_line == 2
        assert config.discharge_review_line == 6

    def test_blank_falls_back_to_the_default(self) -> None:
        """Clearing a field on the screen is a way back, not a way to break it."""
        config = config_from({"warning_line": "  "})
        assert config.warning_line == DEFAULTS["warning_line"]

    def test_unreadable_number_falls_back_rather_than_failing(self) -> None:
        config = config_from({"counting_window_months": "twelve"})
        assert config.counting_window_months == DEFAULTS["counting_window_months"]

    def test_list_reads_from_json(self) -> None:
        config = config_from({"counted_kinds": '["no_show", "late_move"]'})
        assert config.counted_kinds == ["no_show", "late_move"]

    def test_list_also_reads_from_separated_text(self) -> None:
        config = config_from({"counted_kinds": "no_show, late_move"})
        assert config.counted_kinds == ["no_show", "late_move"]

    def test_a_whitespace_only_list_value_falls_back_to_the_default(self) -> None:
        config = config_from({"counted_kinds": "   "})
        assert config.counted_kinds == list(DEFAULTS["counted_kinds"])

    def test_malformed_json_that_looks_like_a_list_falls_back_to_the_default(self) -> None:
        config = config_from({"counted_kinds": "[no_show, "})
        assert config.counted_kinds == list(DEFAULTS["counted_kinds"])

    def test_attribution_default_is_settable(self) -> None:
        assert config_from({"default_attribution": CLINIC}).default_attribution == CLINIC

    def test_incoherent_lines_are_refused(self) -> None:
        with pytest.raises(ConfigError):
            config_from({"warning_line": "5", "discharge_review_line": "3"})

    def test_unknown_attribution_is_refused(self) -> None:
        with pytest.raises(ConfigError):
            config_from({"default_attribution": "whoever"})

    def test_a_stored_iso_floor_parses_into_an_aware_datetime(self) -> None:
        config = config_from({"install_floor": "2026-01-01T00:00:00+00:00"})
        assert config.install_floor is not None
        assert config.install_floor.tzinfo is not None
        assert config.install_floor.year == 2026

    def test_garbage_floor_text_leaves_the_default_standing(self) -> None:
        config = config_from({"install_floor": "not-a-real-moment"})
        assert config.install_floor is None

    def test_no_stored_floor_leaves_the_default_standing(self) -> None:
        assert config_from({}).install_floor is DEFAULTS["install_floor"]

    def test_as_dict_renders_a_stored_floor_back_as_iso_text(self) -> None:
        """The one resolved value that is not already plain text or a number.

        A screen and a JSON response both need this back as text, the same
        text config_from would accept again, rather than the raw datetime
        that plain json.dumps cannot carry.
        """
        config = config_from({"install_floor": "2026-01-01T00:00:00+00:00"})
        assert config.as_dict()["install_floor"] == "2026-01-01T00:00:00+00:00"

    def test_as_dict_leaves_a_missing_floor_as_none(self) -> None:
        assert config_from({}).as_dict()["install_floor"] is None


class TestWritingPolicy:
    """Turning a submitted form into the text a store holds."""

    def test_only_known_settings_survive(self) -> None:
        written = to_raw({"warning_line": 4, "clinic_tag": "x", "something_else": "y"})
        assert "something_else" not in written
        assert written["warning_line"] == "4"

    def test_lists_are_written_as_json(self) -> None:
        written = to_raw({"counted_kinds": ["no_show"]})
        assert written["counted_kinds"] == '["no_show"]'

    def test_empty_list_is_written_as_an_empty_json_array(self) -> None:
        assert to_raw({"warning_task_labels": []})["warning_task_labels"] == "[]"

    def test_none_becomes_empty_text(self) -> None:
        """Which the store reads as delete the row, so the default returns."""
        assert to_raw({"warning_team_id": None})["warning_team_id"] == ""

    def test_a_submitted_floor_is_normalised_to_iso_text(self) -> None:
        written = to_raw({"install_floor": "2026-01-01T00:00:00+00:00"})
        assert written["install_floor"] == "2026-01-01T00:00:00+00:00"

    def test_an_empty_floor_submission_becomes_the_empty_string(self) -> None:
        assert to_raw({"install_floor": ""})["install_floor"] == ""
        assert to_raw({"install_floor": None})["install_floor"] == ""

    def test_an_unparseable_floor_submission_is_refused_silently(self) -> None:
        assert "install_floor" not in to_raw({"install_floor": "not-a-real-moment"})

    def test_a_missing_setting_is_not_written_at_all(self) -> None:
        written = to_raw({"warning_line": 4})
        assert list(written) == ["warning_line"]

    def test_every_editable_setting_round_trips(self) -> None:
        """What the screen can write, stored policy can read back."""
        submitted: dict[str, Any] = {
            "late_cutoff_hours": 12,
            "move_boundary_hours": 6,
            "counting_window_months": 24,
            "holding_window_minutes": 30,
            "run_count": 4,
            "run_window_minutes": 20,
            "warning_line": 2,
            "discharge_review_line": 7,
            "counted_kinds": ["no_show", "late_cancellation"],
            "warning_task_labels": ["urgent"],
            "discharge_review_task_labels": [],
            "default_attribution": CLINIC,
            "warning_team_id": "team-a",
            "discharge_review_team_id": "team-b",
            "clinic_tag": "clinic-said-no",
            "install_floor": "2026-01-01T00:00:00+00:00",
        }
        assert set(submitted) == set(EDITABLE_SETTINGS)

        config = config_from(to_raw(submitted))
        assert config.late_cutoff_hours == 12
        assert config.move_boundary_hours == 6
        assert config.counting_window_months == 24
        assert config.holding_window_minutes == 30
        assert config.run_count == 4
        assert config.run_window_minutes == 20
        assert config.warning_line == 2
        assert config.discharge_review_line == 7
        assert config.counted_kinds == ["no_show", "late_cancellation"]
        assert config.warning_task_labels == ["urgent"]
        assert config.discharge_review_task_labels == []
        assert config.default_attribution == CLINIC
        assert config.warning_team_id == "team-a"
        assert config.discharge_review_team_id == "team-b"
        assert config.clinic_tag == "clinic-said-no"
        assert config.install_floor is not None
        assert config.install_floor.isoformat() == "2026-01-01T00:00:00+00:00"

    def test_a_store_round_trips_through_write_and_read(self) -> None:
        store = FakeStore()
        store.write(to_raw({"warning_line": 2, "discharge_review_line": 9}))
        config = config_from(store.read())
        assert config.warning_line == 2
        assert config.discharge_review_line == 9

    def test_clearing_a_stored_value_restores_the_default(self) -> None:
        store = FakeStore({"warning_line": "2"})
        store.write(to_raw({"warning_line": None}))
        assert config_from(store.read()).warning_line == DEFAULTS["warning_line"]

    def test_access_is_not_policy(self) -> None:
        """Authorization must not be writable from the screen it guards."""
        assert "config_access_staff_ids" not in EDITABLE_SETTINGS
        assert "config_access_staff_ids" not in DEFAULTS


class TestSharedViewPreference:
    """The one stored setting that is shared but is not policy."""

    def test_unset_means_off(self) -> None:
        assert not show_non_counting(FakeStore())

    def test_stored_word_means_on(self) -> None:
        assert show_non_counting(FakeStore({SHOW_NON_COUNTING: "true"}))

    def test_anything_else_means_off(self) -> None:
        assert not show_non_counting(FakeStore({SHOW_NON_COUNTING: "yes"}))

    def test_a_real_boolean_is_understood_too(self) -> None:
        """A page sends JSON and a store holds text, and neither should care."""
        assert truthy(True)
        assert truthy("true")
        assert truthy(" TRUE ")
        assert not truthy(False)
        assert not truthy("")
        assert not truthy(None)

    def test_on_then_off_round_trips(self) -> None:
        store = FakeStore()
        set_show_non_counting(store, True)
        assert show_non_counting(store)
        set_show_non_counting(store, False)
        assert not show_non_counting(store)

    def test_off_is_stored_rather_than_deleted(self) -> None:
        """The store deletes on an empty value, and a deleted name reads as unset.

        Off has to be storable in its own right, otherwise switching it off would
        be indistinguishable from never having touched it and the default would
        decide.
        """
        store = FakeStore()
        set_show_non_counting(store, False)
        assert SHOW_NON_COUNTING in store.values

    def test_it_cannot_reach_policy(self) -> None:
        """It shares the table with policy and has to stay out of policy itself."""
        stored = {SHOW_NON_COUNTING: "true", "warning_line": "4"}
        config = config_from(stored)
        assert config.warning_line == 4
        assert SHOW_NON_COUNTING not in config.as_dict()
        assert SHOW_NON_COUNTING not in to_raw({SHOW_NON_COUNTING: "true"})


class TestStoreContract:
    """The composition root checks its collaborators carry what it calls."""

    def test_a_dictionary_backed_store_satisfies_the_contract(self) -> None:
        assert validate(FakeStore(), STORE_METHODS, "settings store") is not None

    def test_a_store_missing_write_is_refused(self) -> None:
        class ReadOnly:
            def read(self) -> dict[str, str]:
                return {}

        with pytest.raises(TypeError):
            validate(ReadOnly(), STORE_METHODS, "settings store")

    def test_build_wires_policy_from_the_store_it_is_given(self) -> None:
        parts = build(FakeStore({"warning_line": "2", "discharge_review_line": "8"}))
        assert parts["config"].warning_line == 2
        assert parts["config"].discharge_review_line == 8
        assert parts["engine"] is not None
        assert parts["actions"] is not None
