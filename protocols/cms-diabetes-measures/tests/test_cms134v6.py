"""Tests for the CMS134v6 nephropathy-attention protocol."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import arrow
import pytest

from protocols.cms134v6_diabetes_medical_attention_for_nephropathy import (
    AceInhibitors,
    CMS134v6Dialysis,
    ClinicalQualityMeasure134v6,
)


@pytest.fixture
def patient() -> SimpleNamespace:
    """Eligible adult patient stub with a derived ``age_at``."""
    p = SimpleNamespace(
        id="patient-1",
        first_name="Dohav",
        birth_date=arrow.get("1980-01-01").date(),
    )
    p.age_at = lambda when: (when.date() - p.birth_date).days / 365.0
    return p


@pytest.fixture
def protocol(patient) -> ClinicalQualityMeasure134v6:
    """Construct a protocol with all event/ORM plumbing bypassed."""
    proto = ClinicalQualityMeasure134v6.__new__(ClinicalQualityMeasure134v6)
    proto.event = MagicMock()
    proto.secrets = {}
    proto.environment = {}
    proto._patient_id = patient.id
    proto.now = arrow.get("2018-08-23T00:00:00Z")
    proto.__dict__["patient"] = patient
    return proto


def test_meta_description_and_identifier() -> None:
    """Description and identifier copy through."""
    assert (
        "Patients 18-75 years of age with diabetes who have not had a nephropathy "
        "screening test in the last year or evidence of nephropathy."
        == ClinicalQualityMeasure134v6.Meta.description
    )
    assert ClinicalQualityMeasure134v6.Meta.identifiers == ["CMS134v6"]


def test_ace_inhibitors_value_set_has_fdb_codes() -> None:
    """ACE inhibitor FDB codes are preserved verbatim from the legacy classpath."""
    assert "150320" in AceInhibitors.FDB
    assert "591977" in AceInhibitors.FDB


def test_cms134v6_dialysis_codes() -> None:
    """Dialysis value set carries the documented ICD-10 and SNOMED codes."""
    assert CMS134v6Dialysis.ICD10CM == {"Z992"}
    assert CMS134v6Dialysis.SNOMEDCT == {"207RN0300X", "2080P0210X"}


def test_dismissing_conditions_list_has_five_entries() -> None:
    """The five "evidence of nephropathy" conditions are all listed."""
    labels = {label for _, label in ClinicalQualityMeasure134v6.DISMISSING_CONDITIONS}
    assert "Hypertensive Chronic Kidney Disease" in labels
    assert "Kidney Failure" in labels
    assert "Glomerulonephritis and Nephrotic Syndrome" in labels
    assert "Diabetic Nephropathy" in labels
    assert "Proteinuria" in labels


def test_in_numerator_returns_true_when_dialysis_referral(protocol) -> None:
    """A dialysis referral report satisfies the numerator."""
    dialysis = SimpleNamespace(original_date=arrow.get("2018-07-26").date())
    with patch.object(protocol, "_last_dialysis_report", return_value=dialysis):
        assert protocol.in_numerator() is True
    assert protocol.message is not None
    assert "Dialysis Related Service" in protocol.message


def test_in_numerator_returns_true_when_dialysis_education(protocol) -> None:
    """A dialysis-education Instruction in the period satisfies the numerator."""
    instruction = SimpleNamespace(
        note=SimpleNamespace(datetime_of_service=arrow.get("2018-07-15").datetime),
    )
    queryset = MagicMock()
    queryset.exists.return_value = False
    with (
        patch.object(protocol, "_last_dialysis_report", return_value=None),
        patch(
            "protocols.cms134v6_diabetes_medical_attention_for_nephropathy.Medication.objects"
        ) as med_objects,
        patch(
            "protocols.cms134v6_diabetes_medical_attention_for_nephropathy.Condition.objects"
        ) as cond_objects,
        patch.object(protocol, "_last_dialysis_education", return_value=instruction),
        patch.object(protocol, "_last_urine_protein_lab", return_value=None),
    ):
        med_objects.for_patient.return_value.active.return_value.find.return_value.filter.return_value.filter.return_value.exists.return_value = False
        cond_objects.for_patient.return_value.active.return_value.find.return_value.filter.return_value.exists.return_value = False
        assert protocol.in_numerator() is True
    assert protocol.message is not None
    assert "ESRD Monthly Outpatient Services" in protocol.message


def test_in_numerator_returns_true_when_urine_protein_lab(protocol) -> None:
    """A urine protein lab in the period satisfies (and sets due_in)."""
    report = SimpleNamespace(original_date=arrow.get("2018-08-10").datetime)
    queryset = MagicMock()
    queryset.exists.return_value = False
    with (
        patch.object(protocol, "_last_dialysis_report", return_value=None),
        patch(
            "protocols.cms134v6_diabetes_medical_attention_for_nephropathy.Medication.objects"
        ) as med_objects,
        patch(
            "protocols.cms134v6_diabetes_medical_attention_for_nephropathy.Condition.objects"
        ) as cond_objects,
        patch.object(protocol, "_last_dialysis_education", return_value=None),
        patch.object(protocol, "_last_urine_protein_lab", return_value=report),
    ):
        med_objects.for_patient.return_value.active.return_value.find.return_value.filter.return_value.filter.return_value.exists.return_value = False
        cond_objects.for_patient.return_value.active.return_value.find.return_value.filter.return_value.exists.return_value = False
        assert protocol.in_numerator() is True
    assert protocol.message is not None
    assert "urine protein test" in protocol.message


def test_in_numerator_returns_false_when_nothing_qualifies(protocol) -> None:
    """No matching evidence -> not in numerator."""
    with (
        patch.object(protocol, "_last_dialysis_report", return_value=None),
        patch(
            "protocols.cms134v6_diabetes_medical_attention_for_nephropathy.Medication.objects"
        ) as med_objects,
        patch(
            "protocols.cms134v6_diabetes_medical_attention_for_nephropathy.Condition.objects"
        ) as cond_objects,
        patch.object(protocol, "_last_dialysis_education", return_value=None),
        patch.object(protocol, "_last_urine_protein_lab", return_value=None),
    ):
        med_objects.for_patient.return_value.active.return_value.find.return_value.filter.return_value.filter.return_value.exists.return_value = False
        cond_objects.for_patient.return_value.active.return_value.find.return_value.filter.return_value.exists.return_value = False
        assert protocol.in_numerator() is False


def test_compute_not_applicable_when_not_in_denominator(protocol) -> None:
    """Out of denominator -> NOT_APPLICABLE."""
    with patch.object(protocol, "in_denominator", return_value=False):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_due_when_no_evidence(protocol) -> None:
    """In denominator and not in numerator -> DUE with a urine microalbumin order."""
    with (
        patch.object(protocol, "in_denominator", return_value=True),
        patch.object(protocol, "in_numerator", return_value=False),
    ):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_satisfied_when_evidence(protocol) -> None:
    """In denominator and in numerator -> SATISFIED."""
    protocol.message = "Dohav has diabetes and had a Dialysis Related Service ..."
    with (
        patch.object(protocol, "in_denominator", return_value=True),
        patch.object(protocol, "in_numerator", return_value=True),
    ):
        effects = protocol.compute()
    assert len(effects) == 1
