"""Tests for the questionnaire-id resolver and the result summary builder."""

from typing import Any
from unittest.mock import MagicMock, patch

from nutrition_charting.data import questionnaires as q


def setup_function(_fn: Any) -> None:
    q.reset_cache()


def test_questionnaire_sections_registered() -> None:
    # Phase C: three sections; Phase D pass 1 adds NFPE.
    assert set(q.QUESTIONNAIRE_SECTIONS) == {
        "social_diet_history",
        "dietary_intake",
        "nutrition_diagnosis_pes",
        "nfpe",
    }


def test_resolve_returns_none_for_unknown_section() -> None:
    assert q.resolve_questionnaire_id("not_a_section") is None


@patch("nutrition_charting.data.questionnaires.Questionnaire")
def test_resolve_looks_up_by_internal_code(mock_q: MagicMock) -> None:
    qmock = MagicMock()
    qmock.id = "questionnaire-uuid-1"
    mock_q.objects.filter.return_value.order_by.return_value.first.return_value = qmock

    out = q.resolve_questionnaire_id("social_diet_history")

    assert out == "questionnaire-uuid-1"
    mock_q.objects.filter.assert_called_once_with(
        code="NUTRITION_SOCIAL_DIET", code_system="INTERNAL",
    )


@patch("nutrition_charting.data.questionnaires.Questionnaire")
def test_resolve_returns_none_when_questionnaire_not_registered(mock_q: MagicMock) -> None:
    mock_q.objects.filter.return_value.order_by.return_value.first.return_value = None

    assert q.resolve_questionnaire_id("dietary_intake") is None


@patch("nutrition_charting.data.questionnaires.Questionnaire")
def test_resolve_caches_result_per_process(mock_q: MagicMock) -> None:
    qmock = MagicMock()
    qmock.id = "abc-123"
    mock_q.objects.filter.return_value.order_by.return_value.first.return_value = qmock

    first = q.resolve_questionnaire_id("nutrition_diagnosis_pes")
    second = q.resolve_questionnaire_id("nutrition_diagnosis_pes")

    assert first == second == "abc-123"
    # Only one DB hit despite two calls
    assert mock_q.objects.filter.call_count == 1


def test_summarize_section_concatenates_fields_in_order() -> None:
    payload = {
        "appetite": "good",
        "chew_swallow": "intact",
        "nausea_vomiting": "",
        "constipation_diarrhea": None,
        "other_gi": "occasional reflux",
    }

    out = q.summarize_section("social_diet_history", payload)

    # Empty / null fields are dropped; non-empty fields render in spec order
    assert out.startswith("Appetite: good | Chew/Swallow: intact")
    assert "Other GI: occasional reflux" in out
    assert "Nausea/Vomiting" not in out  # empty string filtered
    assert "Constipation/Diarrhea" not in out  # None filtered


def test_summarize_section_returns_empty_for_unknown_section() -> None:
    assert q.summarize_section("not_real", {"x": "y"}) == ""


def test_summarize_section_handles_pes_three_fields() -> None:
    out = q.summarize_section(
        "nutrition_diagnosis_pes",
        {"problem": "Inadequate energy intake", "etiology": "Limited access",
         "signs_symptoms": "5 lb wt loss / 3mo"},
    )
    assert out == (
        "Problem: Inadequate energy intake | "
        "Etiology: Limited access | "
        "Signs/Symptoms: 5 lb wt loss / 3mo"
    )
