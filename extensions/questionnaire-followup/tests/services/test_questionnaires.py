"""Tests for listing the instance's questionnaires and resolving codes to them."""

from collections.abc import Callable
from typing import Any
from unittest.mock import call, patch

from canvas_sdk.v1.data import Questionnaire
from pytest_django import DjangoAssertNumQueries

from questionnaire_followup.services.questionnaires import (
    list_questionnaires,
    resolve_codes,
    resolve_names,
)

MODULE = "questionnaire_followup.services.questionnaires"
LISTED_FIELDS = ("name", "code", "code_system", "use_case_in_charting", "can_originate_in_charting")

# The factory fixture from conftest.py.
MakeQuestionnaire = Callable[..., Questionnaire]


def _row(
    name: str | None,
    code: str | None,
    can_originate: bool | int | None = True,
    code_system: str | None = "LOINC",
    use_case: str | None = "QUES",
) -> dict[str, Any]:
    return {
        "name": name,
        "code": code,
        "code_system": code_system,
        "use_case_in_charting": use_case,
        "can_originate_in_charting": can_originate,
    }


# --------------------------------------------------------------------------- #
#  list_questionnaires
# --------------------------------------------------------------------------- #


def test_list_questionnaires_skips_questionnaires_without_a_code() -> None:
    """A questionnaire no rule could ever point at is left out of the pickers."""
    with patch(f"{MODULE}.Questionnaire") as mock_questionnaire, patch(f"{MODULE}.log") as mock_log:
        mock_questionnaire.objects.filter.return_value.values.return_value = [
            _row("PHQ-9", "44249-1"),
            _row("Blank code", ""),
            _row("Whitespace code", "   "),
            _row("No code", None),
        ]

        result = list_questionnaires()

        assert mock_questionnaire.mock_calls == [
            call.objects.filter(status="AC"),
            call.objects.filter().values(*LISTED_FIELDS),
        ]
        assert mock_log.mock_calls == []
        assert [q["name"] for q in result] == ["PHQ-9"]


def test_list_questionnaires_sorts_by_name_and_fills_blank_fields() -> None:
    """Pickers read alphabetically, with no None where the page expects text."""
    with patch(f"{MODULE}.Questionnaire") as mock_questionnaire, patch(f"{MODULE}.log") as mock_log:
        mock_questionnaire.objects.filter.return_value.values.return_value = [
            _row("phq-9", " 44249-1 ", can_originate=1),
            _row(None, "local-1", can_originate=None, code_system=None, use_case=None),
            _row("GAD-7", "69737-5", can_originate=False),
        ]

        result = list_questionnaires()

        assert mock_questionnaire.mock_calls == [
            call.objects.filter(status="AC"),
            call.objects.filter().values(*LISTED_FIELDS),
        ]
        assert mock_log.mock_calls == []
        assert result == [
            {
                "name": "",
                "code": "local-1",
                "code_system": "",
                "use_case": "",
                "can_originate_in_charting": False,
            },
            {
                "name": "GAD-7",
                "code": "69737-5",
                "code_system": "LOINC",
                "use_case": "QUES",
                "can_originate_in_charting": False,
            },
            {
                "name": "phq-9",
                "code": "44249-1",
                "code_system": "LOINC",
                "use_case": "QUES",
                "can_originate_in_charting": True,
            },
        ]


def test_list_questionnaires_degrades_to_empty_when_the_query_fails() -> None:
    """A failed lookup leaves the pickers empty rather than breaking the page."""
    with patch(f"{MODULE}.Questionnaire") as mock_questionnaire, patch(f"{MODULE}.log") as mock_log:
        mock_questionnaire.objects.filter.return_value.values.side_effect = ValueError("bad field")

        result = list_questionnaires()

        assert mock_questionnaire.mock_calls == [
            call.objects.filter(status="AC"),
            call.objects.filter().values(*LISTED_FIELDS),
        ]
        assert mock_log.mock_calls == [call.warning("questionnaire list failed: bad field")]
        assert result == []


def test_list_questionnaires_reads_real_rows(make_questionnaire: MakeQuestionnaire) -> None:
    """Against the test database, the listed fields exist and inactive ones are left out."""
    make_questionnaire("44249-1", "PHQ-9")
    make_questionnaire("69737-5", "GAD-7", can_originate=False)
    retired = make_questionnaire("00000-0", "Retired form")
    Questionnaire.objects.filter(pk=retired.pk).update(status="IN")

    assert list_questionnaires() == [
        {
            "name": "GAD-7",
            "code": "69737-5",
            "code_system": "LOINC",
            "use_case": "QUES",
            "can_originate_in_charting": False,
        },
        {
            "name": "PHQ-9",
            "code": "44249-1",
            "code_system": "LOINC",
            "use_case": "QUES",
            "can_originate_in_charting": True,
        },
    ]


# --------------------------------------------------------------------------- #
#  resolve_codes
# --------------------------------------------------------------------------- #


def test_resolve_codes_resolves_every_code_in_one_query(
    make_questionnaire: MakeQuestionnaire, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """All the codes a page load needs are resolved together."""
    phq2 = make_questionnaire("55758-7", "PHQ-2")
    phq9 = make_questionnaire("44249-1", "PHQ-9")

    with patch(f"{MODULE}.log") as mock_log:
        with django_assert_num_queries(1):
            result = resolve_codes({"55758-7", "44249-1"})

        assert mock_log.mock_calls == []
        assert {code: q.pk for code, q in result.items()} == {
            "55758-7": phq2.pk,
            "44249-1": phq9.pk,
        }


def test_resolve_codes_loads_only_what_the_handler_reads(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """The questionnaire's other columns are never fetched on the portal's hot path."""
    make_questionnaire("44249-1", "PHQ-9")

    questionnaire = resolve_codes({"44249-1"})["44249-1"]

    assert questionnaire.get_deferred_fields() >= {
        "scoring_function_name",
        "search_tags",
        "carry_forward",
        "expected_completion_time",
    }
    assert questionnaire.name == "PHQ-9"
    assert questionnaire.can_originate_in_charting is True


def test_resolve_codes_leaves_out_missing_and_inactive_codes(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """A code this instance does not have, or has only retired, resolves to nothing."""
    make_questionnaire("44249-1", "PHQ-9")
    retired = make_questionnaire("00000-0", "Retired form")
    Questionnaire.objects.filter(pk=retired.pk).update(status="IN")

    with patch(f"{MODULE}.log") as mock_log:
        result = resolve_codes({"44249-1", "00000-0", "99999-9"})

        assert mock_log.mock_calls == []
        assert set(result) == {"44249-1"}


def test_resolve_codes_refuses_an_ambiguous_code(make_questionnaire: MakeQuestionnaire) -> None:
    """Two active questionnaires sharing a code are not guessed between; others still resolve."""
    make_questionnaire("44249-1", "PHQ-9")
    make_questionnaire("44249-1", "PHQ-9 (copy)")
    make_questionnaire("55758-7", "PHQ-2")

    with patch(f"{MODULE}.log") as mock_log:
        result = resolve_codes({"44249-1", "55758-7"})

        assert mock_log.mock_calls == [
            call.warning(
                "questionnaire code=44249-1 matches multiple active questionnaires; "
                "refusing to guess which one a pairing meant"
            )
        ]
        assert set(result) == {"55758-7"}


def test_resolve_codes_without_a_code_does_not_query(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Blank codes resolve to nothing without touching the database."""
    with patch(f"{MODULE}.log") as mock_log:
        with django_assert_num_queries(0):
            result = resolve_codes({""})

        assert mock_log.mock_calls == []
        assert result == {}


def test_resolve_codes_returns_nothing_when_the_query_fails() -> None:
    """A failed lookup resolves nothing and is logged."""
    with patch(f"{MODULE}.Questionnaire") as mock_questionnaire, patch(f"{MODULE}.log") as mock_log:
        mock_questionnaire.objects.filter.return_value.only.side_effect = ValueError("bad lookup")

        result = resolve_codes({"44249-1"})

        assert mock_questionnaire.mock_calls == [
            call.objects.filter(code__in={"44249-1"}, status="AC"),
            call.objects.filter().only("dbid", "id", "code", "name", "can_originate_in_charting"),
        ]
        assert mock_log.mock_calls == [
            call.warning("questionnaire resolve failed for codes=['44249-1']: bad lookup")
        ]
        assert result == {}


# --------------------------------------------------------------------------- #
#  resolve_names - used only to seed the default pairings
# --------------------------------------------------------------------------- #


def test_a_name_resolves_to_the_code_this_instance_carries(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """The whole point: seed from what the instance loaded, not a code guessed ahead.

    A real Canvas instance was found carrying PHQ-2 as 58120-7 and GAD-2 under a
    SNOMED code, while the published panel codes this plugin ships matched neither.
    """
    make_questionnaire("58120-7", "PHQ-2")
    make_questionnaire("836551000000102", "GAD-2")

    assert resolve_names({"PHQ-2", "GAD-2"}) == {
        "PHQ-2": "58120-7",
        "GAD-2": "836551000000102",
    }


def test_matching_ignores_case_and_surrounding_space(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """As loose as this gets - a near-match on a clinical instrument is a wrong one."""
    make_questionnaire("58120-7", "  phq-2 ")

    assert resolve_names({"PHQ-2"}) == {"PHQ-2": "58120-7"}


def test_a_name_this_instance_does_not_have_resolves_to_nothing() -> None:
    """The caller then keeps the published code, which the editor flags if it is wrong."""
    assert resolve_names({"PHQ-2"}) == {}


def test_a_name_on_two_different_codes_is_refused(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """Two instruments share a name: seeding either one would be a guess."""
    make_questionnaire("58120-7", "PHQ-2")
    make_questionnaire("55758-7", "PHQ-2")

    with patch(f"{MODULE}.log") as mock_log:
        result = resolve_names({"PHQ-2"})

        assert result == {}
        assert mock_log.mock_calls == [
            call.warning(
                "questionnaire name='PHQ-2' matches active questionnaires with "
                "different codes ['55758-7', '58120-7']; not seeding a pairing from it"
            )
        ]


def test_two_questionnaires_sharing_one_name_and_code_still_resolve(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """Nothing is being guessed between them - there is only one code to seed."""
    make_questionnaire("58120-7", "PHQ-2")
    make_questionnaire("58120-7", "PHQ-2")

    assert resolve_names({"PHQ-2"}) == {"PHQ-2": "58120-7"}


def test_retired_questionnaires_are_not_seeded_from(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """Only active questionnaires; a retired one must not become a seeded pairing."""
    retired = make_questionnaire("55758-7", "PHQ-2")
    Questionnaire.objects.filter(pk=retired.pk).update(status="RT")
    make_questionnaire("58120-7", "PHQ-2")

    assert resolve_names({"PHQ-2"}) == {"PHQ-2": "58120-7"}


def test_a_questionnaire_with_no_code_is_skipped(
    make_questionnaire: MakeQuestionnaire,
) -> None:
    """An unaddressable questionnaire cannot be seeded, and must not hide a usable one."""
    make_questionnaire("", "PHQ-2")
    make_questionnaire("58120-7", "PHQ-2")

    assert resolve_names({"PHQ-2"}) == {"PHQ-2": "58120-7"}


def test_blank_names_cost_no_query(django_assert_num_queries: DjangoAssertNumQueries) -> None:
    """Nothing to look up, so nothing is looked up."""
    with django_assert_num_queries(0):
        assert resolve_names({"", "   "}) == {}


def test_resolving_every_name_costs_one_query(
    make_questionnaire: MakeQuestionnaire, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """One query however many names are asked for - never one lookup per name."""
    for code, name in [("58120-7", "PHQ-2"), ("44249-1", "PHQ-9"), ("69737-5", "GAD-7")]:
        make_questionnaire(code, name)

    with django_assert_num_queries(1):
        assert resolve_names({"PHQ-2", "PHQ-9", "GAD-2", "GAD-7"}) == {
            "PHQ-2": "58120-7",
            "PHQ-9": "44249-1",
            "GAD-7": "69737-5",
        }


def test_a_failed_name_lookup_falls_back_to_the_published_codes() -> None:
    """Seeding must never raise: a broken lookup leaves the shipped codes in place."""
    with (
        patch(f"{MODULE}.Questionnaire") as mock_questionnaire,
        patch(f"{MODULE}.log") as mock_log,
    ):
        mock_questionnaire.objects.filter.side_effect = AttributeError("boom")

        result = resolve_names({"PHQ-2"})

        assert result == {}
        assert mock_log.mock_calls == [
            call.warning("questionnaire name lookup failed for names=['PHQ-2']: boom")
        ]
