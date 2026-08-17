"""Patient name search behind the roster's add form."""

from datetime import date
from unittest.mock import MagicMock, patch

from scheduling_waitlist.constants import (
    MAX_PATIENT_SEARCH_RESULTS,
    MIN_PATIENT_SEARCH_LENGTH,
)
from scheduling_waitlist.services.patients import search_patients

MODULE = "scheduling_waitlist.services.patients"


def _patient(first="Ada", last="Lovelace", uuid="p-1", birth_date=date(1815, 12, 10)):
    record = MagicMock()
    record.id = uuid
    record.first_name = first
    record.last_name = last
    record.birth_date = birth_date
    return record


def _run(term, results=None):
    """Search with a scripted queryset, returning the captured filter args."""
    with patch(f"{MODULE}.Patient") as model:
        chain = model.objects.filter.return_value.order_by.return_value
        chain.__getitem__.return_value = results or []
        found = search_patients(term)
    return found, model


class TestQueryLength:
    def test_a_query_below_the_minimum_returns_nothing(self):
        # The picker forwards keystrokes; one character must not scan the table.
        found, model = _run("a" * (MIN_PATIENT_SEARCH_LENGTH - 1))

        assert found == []
        model.objects.filter.assert_not_called()

    def test_an_empty_query_returns_nothing(self):
        found, model = _run("")

        assert found == []
        model.objects.filter.assert_not_called()

    def test_whitespace_only_is_treated_as_empty(self):
        found, model = _run("   ")

        assert found == []
        model.objects.filter.assert_not_called()

    def test_a_query_at_the_minimum_runs(self):
        _, model = _run("a" * MIN_PATIENT_SEARCH_LENGTH, results=[_patient()])

        model.objects.filter.assert_called_once()


class TestMatching:
    def test_first_and_last_name_are_matched_in_one_query(self):
        # Two queries merged in Python would cost a round trip and break the cap.
        _, model = _run("love", results=[_patient()])

        assert model.objects.filter.call_count == 1
        predicate = model.objects.filter.call_args.args[0]
        assert predicate.connector == "OR"
        assert predicate.leaves() == [
            {"first_name__icontains": "love"},
            {"last_name__icontains": "love"},
        ]

    def test_only_active_patients_are_searched(self):
        _, model = _run("love", results=[_patient()])

        assert model.objects.filter.call_args.kwargs["active"] is True

    def test_the_term_is_trimmed_before_matching(self):
        _, model = _run("  love  ", results=[_patient()])

        predicate = model.objects.filter.call_args.args[0]
        assert predicate.leaves()[0] == {"first_name__icontains": "love"}

    def test_results_are_capped(self):
        _, model = _run("love", results=[_patient()])

        window = model.objects.filter.return_value.order_by.return_value
        assert window.__getitem__.call_args.args[0] == slice(
            None, MAX_PATIENT_SEARCH_RESULTS
        )

    def test_results_are_ordered_by_name_for_a_stable_picker(self):
        _, model = _run("love", results=[_patient()])

        assert model.objects.filter.return_value.order_by.call_args.args == (
            "last_name",
            "first_name",
            "dbid",
        )


class TestSerialization:
    def test_a_match_carries_id_name_and_birth_date(self):
        found, _ = _run("love", results=[_patient()])

        assert found == [
            {"id": "p-1", "name": "Ada Lovelace", "birth_date": "1815-12-10"}
        ]

    def test_a_patient_with_no_birth_date_renders_an_empty_string(self):
        # "None" in a patient picker reads as a broken plugin.
        found, _ = _run("love", results=[_patient(birth_date=None)])

        assert found[0]["birth_date"] == ""

    def test_an_unnamed_patient_still_gets_a_label(self):
        found, _ = _run("love", results=[_patient(first="", last="")])

        assert found[0]["name"] == "Unnamed patient"

    def test_no_matches_yields_an_empty_list(self):
        found, _ = _run("nobody", results=[])

        assert found == []
