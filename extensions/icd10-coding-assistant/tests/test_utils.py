"""Tests for icd10_coding_assistant.utils."""

from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.test_utils.factories.user import CanvasUserFactory
from canvas_sdk.v1.data.condition import ClinicalStatus

from icd10_coding_assistant.utils import get_conditions_missing_icd10
from tests.factories import ConditionCodingFactory, ConditionFactory


def test_get_conditions_missing_icd10_calls_correct_chain() -> None:
    """Verify the queryset chain: for_patient → active → filter(surgical=False)
    → prefetch_related → exclude(ICD-10)."""
    mock_qs = MagicMock()
    mock_qs.active.return_value = mock_qs
    mock_qs.filter.return_value = mock_qs
    mock_qs.prefetch_related.return_value = mock_qs
    mock_qs.exclude.return_value = [MagicMock()]  # simulate one result

    with patch("icd10_coding_assistant.utils.Condition") as mock_condition_cls:
        mock_condition_cls.objects.for_patient.return_value = mock_qs

        result = get_conditions_missing_icd10("patient-abc")

    mock_condition_cls.objects.for_patient.assert_called_once_with("patient-abc")
    mock_qs.active.assert_called_once()
    mock_qs.filter.assert_called_once_with(surgical=False)
    mock_qs.prefetch_related.assert_called_once_with("codings")
    # exclude should be called with ICD-10 system constant
    mock_qs.exclude.assert_called_once()
    exclude_kwargs = mock_qs.exclude.call_args[1]
    assert exclude_kwargs.get("codings__system") == "ICD-10"

    assert len(result) == 1


def test_get_conditions_missing_icd10_returns_list() -> None:
    """Result must be a list, not a lazy queryset."""
    with patch("icd10_coding_assistant.utils.Condition") as mock_condition_cls:
        mock_qs = MagicMock()
        mock_qs.active.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.exclude.return_value = []
        mock_condition_cls.objects.for_patient.return_value = mock_qs

        result = get_conditions_missing_icd10("patient-xyz")

    assert isinstance(result, list)


@pytest.mark.django_db
def test_get_conditions_missing_icd10_db() -> None:
    """Real DB test: prove each filter branch (active, committed, entered_in_error,
    surgical, clinical_status, ICD-10 already coded) against actual rows.

    Only condition (A) — active, committed, non-surgical, SNOMED-only — must appear.
    """
    from canvas_sdk.test_utils.factories.patient import PatientFactory

    patient = PatientFactory.create()
    patient_id: str = patient.id

    snomed_system = "http://snomed.info/sct"
    icd10_system = "ICD-10"

    # (A) active + committed + SNOMED-only coding → INCLUDED
    cond_a = ConditionFactory.create(patient=patient)
    ConditionCodingFactory.create(condition=cond_a, system=snomed_system)

    # (B) active + committed + ICD-10 coding → EXCLUDED (already has ICD-10)
    cond_b = ConditionFactory.create(patient=patient)
    ConditionCodingFactory.create(condition=cond_b, system=icd10_system)

    # (C) active + committed + SNOMED, but entered_in_error set → EXCLUDED
    error_user = CanvasUserFactory.create()
    cond_c = ConditionFactory.create(patient=patient, entered_in_error=error_user)
    ConditionCodingFactory.create(condition=cond_c, system=snomed_system)

    # (D) active + SNOMED, but committer=None (uncommitted) → EXCLUDED
    cond_d = ConditionFactory.create(patient=patient, committer=None)
    ConditionCodingFactory.create(condition=cond_d, system=snomed_system)

    # (E) committed + SNOMED, but clinical_status=resolved → EXCLUDED
    cond_e = ConditionFactory.create(
        patient=patient, clinical_status=ClinicalStatus.RESOLVED
    )
    ConditionCodingFactory.create(condition=cond_e, system=snomed_system)

    # (F) active + committed + SNOMED, but surgical=True → EXCLUDED
    cond_f = ConditionFactory.create(patient=patient, surgical=True)
    ConditionCodingFactory.create(condition=cond_f, system=snomed_system)

    result = get_conditions_missing_icd10(patient_id)

    assert isinstance(result, list)
    assert len(result) == 1, (
        f"Expected exactly 1 condition, got {len(result)}: {[c.dbid for c in result]}"
    )
    assert result[0].dbid == cond_a.dbid
