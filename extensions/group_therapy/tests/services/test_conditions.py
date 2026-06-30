"""Tests for group_therapy.services.conditions active-diagnosis lookup."""

from unittest.mock import MagicMock, patch

from group_therapy.services.conditions import active_conditions, default_condition_id

ICD_URL = "http://hl7.org/fhir/sid/icd-10-cm"


def _coding(system, code, display):
    coding = MagicMock()
    coding.system, coding.code, coding.display = system, code, display
    return coding


def _condition(cid, codings):
    cond = MagicMock()
    cond.id = cid
    cond.codings.all.return_value = codings
    return cond


def test_default_condition_id_single():
    assert default_condition_id([{"id": "x", "icd10_code": "F41.1", "display": "GAD"}]) == "x"


def test_default_condition_id_multiple_returns_none():
    assert default_condition_id([{"id": "a"}, {"id": "b"}]) is None


def test_default_condition_id_empty_returns_none():
    assert default_condition_id([]) is None


@patch("group_therapy.services.conditions.CodeConstants")
@patch("group_therapy.services.conditions.Condition")
def test_active_conditions_returns_icd10_only(mock_condition, mock_cc):
    mock_cc.URL_ICD10 = ICD_URL
    cond = _condition(
        "c1",
        [
            _coding("http://snomed.info/sct", "44054006", "snomed dx"),
            _coding(ICD_URL, "F41.1", "Generalized anxiety disorder"),
        ],
    )
    qs = MagicMock()
    qs.prefetch_related.return_value = [cond]
    mock_condition.objects.for_patient.return_value.committed.return_value = qs

    result = active_conditions("pat1")

    assert result == [{"id": "c1", "icd10_code": "F41.1", "display": "Generalized anxiety disorder"}]
    mock_condition.objects.for_patient.assert_called_once_with("pat1")
    qs.prefetch_related.assert_called_once_with("codings")


@patch("group_therapy.services.conditions.CodeConstants")
@patch("group_therapy.services.conditions.Condition")
def test_active_conditions_skips_condition_without_icd10(mock_condition, mock_cc):
    mock_cc.URL_ICD10 = ICD_URL
    cond = _condition("c2", [_coding("http://snomed.info/sct", "999", "snomed only")])
    qs = MagicMock()
    qs.prefetch_related.return_value = [cond]
    mock_condition.objects.for_patient.return_value.committed.return_value = qs

    assert active_conditions("pat1") == []


@patch("group_therapy.services.conditions.CodeConstants")
@patch("group_therapy.services.conditions.Condition")
def test_active_conditions_degrades_to_empty_on_lookup_error(mock_condition, mock_cc):
    mock_cc.URL_ICD10 = ICD_URL
    mock_condition.objects.for_patient.side_effect = AttributeError("boom")

    assert active_conditions("pat1") == []
