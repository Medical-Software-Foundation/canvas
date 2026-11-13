"""The chart banner that says a patient is already on the waitlist."""

from unittest.mock import MagicMock, patch

import pytest

from scheduling_waitlist.constants import BANNER_KEY, BANNER_NARRATIVE_MAX, ROSTER_URL
from scheduling_waitlist.services.banner import (
    banner_effects,
    banner_effects_for_entry,
    compose_narrative,
)

MODULE = "scheduling_waitlist.services.banner"


def _patient(dbid=1, uuid="patient-uuid"):
    return MagicMock(dbid=dbid, id=uuid)


def _entry(type_name="Follow-up"):
    entry = MagicMock()
    # ``name`` is a MagicMock constructor kwarg, so it has to be set after.
    entry.note_type = MagicMock(code="")
    entry.note_type.name = type_name
    return entry


def _entry_any_type():
    entry = MagicMock()
    entry.note_type = None
    return entry


class TestNarrative:
    def test_a_single_entry_names_the_service(self):
        assert compose_narrative([_entry("Follow-up")]) == (
            "On the scheduling waitlist for Follow-up"
        )

    def test_several_entries_are_counted_rather_than_listed(self):
        # Listing them would blow the length cap on any realistic set of names.
        narrative = compose_narrative([_entry("A"), _entry("B"), _entry("C")])

        assert narrative == "On the scheduling waitlist for 3 appointment types"

    def test_a_null_service_reads_as_any_rather_than_unspecified(self):
        # A null note type is a real preference -- "any type will do" -- not
        # missing data, and the banner should not imply the row is broken.
        assert compose_narrative([_entry_any_type()]) == (
            "On the scheduling waitlist for Any appointment type"
        )

    def test_an_overlong_service_name_is_truncated_not_dropped(self):
        narrative = compose_narrative([_entry("Extremely " * 20 + "Long Service")])

        assert len(narrative) <= BANNER_NARRATIVE_MAX
        assert narrative.endswith("…")

    def test_the_truncated_narrative_is_accepted_by_the_effect(self):
        # The real effect raises above the cap, so truncation has to be enough
        # on its own -- this is the test that would catch an off-by-one.
        entries = [_entry("Extremely " * 20 + "Long Service")]

        with patch(f"{MODULE}.live_entries_for_patient", return_value=entries):
            effects = banner_effects(_patient())

        assert effects[0].narrative == compose_narrative(entries)


class TestAddingTheBanner:
    def test_a_waiting_patient_gets_a_chart_banner(self):
        with patch(f"{MODULE}.live_entries_for_patient", return_value=[_entry()]):
            effects = banner_effects(_patient(uuid="p-1"))

        assert len(effects) == 1
        assert effects[0].patient_id == "p-1"
        assert effects[0].key == BANNER_KEY
        assert [p.value for p in effects[0].placement] == ["chart"]
        assert effects[0].intent.value == "info"

    def test_the_banner_links_to_the_roster(self):
        # The practice-wide list, not a view of this one patient: the ticket's
        # filters are service, provider and location, and a patient-scoped roster
        # was a decision that got reverted.
        with patch(f"{MODULE}.live_entries_for_patient", return_value=[_entry()]):
            effects = banner_effects(_patient(uuid="p-7"))

        assert effects[0].href == ROSTER_URL
        assert "patient=" not in effects[0].href


class TestClearingTheBanner:
    def test_a_patient_with_nothing_live_has_the_banner_removed(self):
        with patch(f"{MODULE}.live_entries_for_patient", return_value=[]):
            effects = banner_effects(_patient(uuid="p-2"))

        assert len(effects) == 1
        assert effects[0].patient_id == "p-2"
        assert effects[0].key == BANNER_KEY
        assert not hasattr(effects[0], "narrative")

    def test_removal_uses_the_same_key_that_created_it(self):
        with patch(f"{MODULE}.live_entries_for_patient", return_value=[_entry()]):
            added = banner_effects(_patient())
        with patch(f"{MODULE}.live_entries_for_patient", return_value=[]):
            removed = banner_effects(_patient())

        assert added[0].key == removed[0].key


class TestGuards:
    def test_a_patient_without_a_uuid_yields_nothing(self):
        # A banner keyed on a missing patient could never be removed again.
        with patch(f"{MODULE}.live_entries_for_patient", return_value=[_entry()]):
            assert banner_effects(MagicMock(dbid=1, id=None)) == []

    def test_a_missing_patient_yields_nothing(self):
        assert banner_effects(None) == []

    def test_the_entry_helper_reads_the_patient_off_the_entry(self):
        entry = MagicMock()
        entry.patient = _patient(uuid="from-entry")

        with patch(f"{MODULE}.live_entries_for_patient", return_value=[_entry()]):
            effects = banner_effects_for_entry(entry)

        assert effects[0].patient_id == "from-entry"

    def test_an_entry_without_a_patient_yields_nothing(self):
        entry = MagicMock()
        entry.patient = None

        assert banner_effects_for_entry(entry) == []


class TestEffectContract:
    def test_a_narrative_over_the_cap_is_refused_by_the_effect(self):
        from canvas_sdk.effects.banner_alert.add_banner_alert import AddBannerAlert

        with pytest.raises(ValueError):
            AddBannerAlert(
                patient_id="p",
                key=BANNER_KEY,
                narrative="x" * (BANNER_NARRATIVE_MAX + 1),
                placement=[AddBannerAlert.Placement.CHART],
                intent=AddBannerAlert.Intent.INFO,
            )
