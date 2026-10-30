"""Tests for the chart_review pre-fill aggregator."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _coding(code: str, system: str, display: str) -> MagicMock:
    return MagicMock(code=code, system=system, display=display)


def _orm_obj(id_: str, codings: list, **extra) -> MagicMock:
    """Build a fake ORM instance with a `codings` related-manager-like."""
    obj = MagicMock(id=id_, **extra)
    related = MagicMock()
    related.all.return_value = codings
    obj.codings = related
    return obj


def _patched_qs(rows: list) -> MagicMock:
    """Construct a chained queryset mock that yields ``rows``.

    chart_review now caps each queryset with ``[:MAX_PREFILL_ROWS]`` so the
    mock needs to handle ``__getitem__`` — returning self keeps the same
    iter chain for the production code's ``for x in qs:`` loop.
    """
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    qs.prefetch_related.return_value = qs
    qs.__getitem__.return_value = qs
    qs.__iter__.return_value = iter(rows)
    return qs


# ---------------------------------------------------------------------------
# active_conditions
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.chart_review.Condition")
def test_active_conditions_returns_id_code_display(MockCondition, patient_id):
    from intake_chart_app.data.chart_review import active_conditions
    rows = [
        _orm_obj("cond-1", [_coding("I10", "http://hl7.org/fhir/sid/icd-10", "Hypertension")]),
        _orm_obj("cond-2", [_coding("E11.9", "http://hl7.org/fhir/sid/icd-10", "Type 2 Diabetes")]),
    ]
    MockCondition.objects.for_patient.return_value = _patched_qs(rows)

    result = active_conditions(patient_id)

    MockCondition.objects.for_patient.assert_called_once_with(patient_id)
    assert result == [
        {"id": "cond-1", "code": "I10", "system": "http://hl7.org/fhir/sid/icd-10", "display": "Hypertension"},
        {"id": "cond-2", "code": "E11.9", "system": "http://hl7.org/fhir/sid/icd-10", "display": "Type 2 Diabetes"},
    ]


@patch("intake_chart_app.data.chart_review.Condition")
def test_active_conditions_filters_clinical_status_and_retracted(MockCondition, patient_id):
    from intake_chart_app.data.chart_review import active_conditions
    qs = _patched_qs([])
    MockCondition.objects.for_patient.return_value = qs
    active_conditions(patient_id)
    qs.filter.assert_called_once_with(
        clinical_status="active",
        deleted=False,
        entered_in_error__isnull=True,
        committer__isnull=False,
    )


@patch("intake_chart_app.data.chart_review.Condition")
def test_active_conditions_drops_rows_with_empty_display(MockCondition, patient_id):
    from intake_chart_app.data.chart_review import active_conditions
    rows = [
        _orm_obj("cond-1", [_coding("I10", "icd10", "")]),     # empty display → drop
        _orm_obj("cond-2", []),                                  # no codings → drop
        _orm_obj("cond-3", [_coding("E11.9", "icd10", "Diabetes")]),
    ]
    MockCondition.objects.for_patient.return_value = _patched_qs(rows)
    result = active_conditions(patient_id)
    assert [r["id"] for r in result] == ["cond-3"]


def test_active_conditions_blank_patient_id_short_circuits():
    from intake_chart_app.data.chart_review import active_conditions
    assert active_conditions("") == []


# ---------------------------------------------------------------------------
# active_allergies
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.chart_review.AllergyIntolerance")
def test_active_allergies_returns_allergen_severity_narrative(MockAI, patient_id):
    from intake_chart_app.data.chart_review import active_allergies
    rows = [
        _orm_obj(
            "a-1",
            [_coding("7980", "rxnorm", "Penicillin")],
            narrative="anaphylaxis on dose 1",
            severity="severe",
        ),
    ]
    MockAI.objects.for_patient.return_value = _patched_qs(rows)
    result = active_allergies(patient_id)
    assert result == [{
        "id": "a-1",
        "allergen": "Penicillin",
        "narrative": "anaphylaxis on dose 1",
        "severity": "severe",
    }]


@patch("intake_chart_app.data.chart_review.AllergyIntolerance")
def test_active_allergies_filters_status_and_retracted(MockAI, patient_id):
    from intake_chart_app.data.chart_review import active_allergies
    qs = _patched_qs([])
    MockAI.objects.for_patient.return_value = qs
    active_allergies(patient_id)
    qs.filter.assert_called_once_with(
        status="active",
        deleted=False,
        entered_in_error__isnull=True,
        committer__isnull=False,
    )


@patch("intake_chart_app.data.chart_review.AllergyIntolerance")
def test_active_allergies_falls_back_to_narrative_when_no_coding(MockAI, patient_id):
    """If the allergy has no coding (or empty display), the narrative becomes
    the allergen label so MA still sees something actionable."""
    from intake_chart_app.data.chart_review import active_allergies
    rows = [
        _orm_obj("a-1", [], narrative="latex", severity="moderate"),
    ]
    MockAI.objects.for_patient.return_value = _patched_qs(rows)
    result = active_allergies(patient_id)
    assert result == [{
        "id": "a-1",
        "allergen": "latex",
        "narrative": "latex",
        "severity": "moderate",
    }]


@patch("intake_chart_app.data.chart_review.AllergyIntolerance")
def test_active_allergies_drops_rows_with_no_label(MockAI, patient_id):
    from intake_chart_app.data.chart_review import active_allergies
    rows = [_orm_obj("a-1", [], narrative="", severity="")]
    MockAI.objects.for_patient.return_value = _patched_qs(rows)
    assert active_allergies(patient_id) == []


# ---------------------------------------------------------------------------
# active_medications (uses Medication.objects.for_patient(p).active())
# ---------------------------------------------------------------------------


def _active_qs(rows: list) -> MagicMock:
    """Mock the for_patient(...).active().filter(...).prefetch_related chain.

    The final slice operator on the queryset returns the same iterable mock
    (see ``_patched_qs`` for the rationale).
    """
    inner = MagicMock()
    inner.filter.return_value = inner
    inner.prefetch_related.return_value = inner
    inner.__getitem__.return_value = inner
    inner.__iter__.return_value = iter(rows)

    active_chain = MagicMock()
    active_chain.active.return_value = inner

    return active_chain, inner


@patch("intake_chart_app.data.chart_review.Medication")
def test_active_medications_returns_display_and_sig(MockMed, patient_id):
    from intake_chart_app.data.chart_review import active_medications
    rows = [
        _orm_obj(
            "m-1",
            [_coding("314076", "rxnorm", "Lisinopril 10 MG Oral Tablet")],
            clinical_quantity_description="1 tablet daily",
            quantity_qualifier_description="",
        ),
    ]
    chain, _inner = _active_qs(rows)
    MockMed.objects.for_patient.return_value = chain
    result = active_medications(patient_id)
    MockMed.objects.for_patient.assert_called_once_with(patient_id)
    chain.active.assert_called_once_with()
    assert result == [{
        "id": "m-1",
        "display": "Lisinopril 10 MG Oral Tablet",
        "sig": "1 tablet daily",
    }]


@patch("intake_chart_app.data.chart_review.Medication")
def test_active_medications_calls_for_patient_then_active_then_filter(MockMed, patient_id):
    """Verify the canonical chain: for_patient(p).active().filter(...)."""
    from intake_chart_app.data.chart_review import active_medications
    chain, inner = _active_qs([])
    MockMed.objects.for_patient.return_value = chain
    active_medications(patient_id)
    inner.filter.assert_called_once_with(
        deleted=False,
        entered_in_error__isnull=True,
        committer__isnull=False,
    )


@patch("intake_chart_app.data.chart_review.Medication")
def test_active_medications_falls_back_to_qualifier_for_sig(MockMed, patient_id):
    from intake_chart_app.data.chart_review import active_medications
    rows = [
        _orm_obj(
            "m-1",
            [_coding("rx", "rxnorm", "Atorvastatin 20 MG")],
            clinical_quantity_description="",
            quantity_qualifier_description="30 tablets",
        ),
    ]
    chain, _inner = _active_qs(rows)
    MockMed.objects.for_patient.return_value = chain
    result = active_medications(patient_id)
    assert result[0]["sig"] == "30 tablets"


@patch("intake_chart_app.data.chart_review.Medication")
def test_active_medications_drops_rows_with_no_display(MockMed, patient_id):
    from intake_chart_app.data.chart_review import active_medications
    rows = [_orm_obj("m-1", [], clinical_quantity_description="", quantity_qualifier_description="")]
    chain, _inner = _active_qs(rows)
    MockMed.objects.for_patient.return_value = chain
    assert active_medications(patient_id) == []
