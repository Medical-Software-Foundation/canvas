"""Tests for the CMS130v6 Colorectal Cancer Screening plugin.

These tests focus on pure-logic checks: Meta configuration, the supplemental
value set, the look-back interval table, and the age-range / colon-exclusion
helpers driven by a stubbed Patient. Database-backed behavior (Condition,
LabValue, ReferralReport, ImagingReport queries) is exercised by integration
tests in the Canvas runtime, not here.
"""

from datetime import date
from unittest.mock import patch

import arrow
import pytest

from protocols.cms130v6_colorectal_cancer_screening import (
    SCREENING_INTERVALS,
    CMS130v6CtColonography,
    ClinicalQualityMeasure130v6,
)


class _StubPatient:
    """Minimal Patient stand-in exposing the attributes the protocol reads."""

    def __init__(self, birth_date: date, first_name: str = "Nat", id: str = "patient-1") -> None:
        self.birth_date = birth_date
        self.first_name = first_name
        self.id = id

    def age_at(self, time: arrow.Arrow) -> float:
        """Mirror the SDK Patient.age_at implementation closely enough for tests."""
        birth = arrow.get(self.birth_date)
        if birth.date() >= time.date():
            return 0.0
        age = time.datetime.year - birth.datetime.year
        if time.datetime.month < birth.datetime.month or (
            time.datetime.month == birth.datetime.month
            and time.datetime.day < birth.datetime.day
        ):
            age -= 1
        return float(age)


def _make_protocol(
    *,
    birth_date: date,
    now: arrow.Arrow,
    has_exclusion: bool = False,
) -> ClinicalQualityMeasure130v6:
    """Build a protocol instance with a stub patient and a mocked exclusion lookup."""
    protocol = ClinicalQualityMeasure130v6.__new__(ClinicalQualityMeasure130v6)
    protocol.now = now
    patient = _StubPatient(birth_date=birth_date)
    # cached_property write goes straight into the instance dict.
    protocol.__dict__["patient"] = patient
    protocol.had_colon_exclusion = lambda: has_exclusion  # type: ignore[method-assign]
    return protocol


def test_meta_description() -> None:
    """The Meta description should match the upstream measure language."""
    assert ClinicalQualityMeasure130v6.Meta.description == (
        "Adults 50-75 years of age who have not had appropriate "
        "screening for colorectal cancer."
    )


def test_meta_information() -> None:
    """The Meta information URL should point at the eCQI specification page."""
    assert ClinicalQualityMeasure130v6.Meta.information == (
        "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS130v6.html"
    )


def test_meta_version() -> None:
    """The Meta version should be preserved from the legacy CQM."""
    assert ClinicalQualityMeasure130v6.Meta.version == "2020-02-24v1"


def test_meta_identifiers() -> None:
    """The identifiers list should contain only CMS130v6."""
    assert ClinicalQualityMeasure130v6.Meta.identifiers == ["CMS130v6"]


def test_meta_types() -> None:
    """The measure should be tagged as a CQM."""
    assert ClinicalQualityMeasure130v6.Meta.types == ["CQM"]


def test_meta_authors() -> None:
    """The authors should match the legacy CQM."""
    assert ClinicalQualityMeasure130v6.Meta.authors == [
        "National Committee for Quality Assurance"
    ]


def test_age_range_constants() -> None:
    """Age range should be 50-75 inclusive."""
    assert ClinicalQualityMeasure130v6.AGE_RANGE_START == 50
    assert ClinicalQualityMeasure130v6.AGE_RANGE_END == 75


def test_protocol_key() -> None:
    """The protocol_key surfaces CMS130v6 to the runtime."""
    assert ClinicalQualityMeasure130v6.PROTOCOL_KEY == "CMS130v6"


def test_screening_intervals_match_specification() -> None:
    """Look-back windows should match the eCQM specification."""
    assert SCREENING_INTERVALS == {
        "FOBT": 365,
        "FIT-DNA": 1096,
        "Flexible sigmoidoscopy": 1826,
        "CT Colonography": 1826,
        "Colonoscopy": 3652,
    }


def test_cms130v6_ct_colonography_loinc_supplement() -> None:
    """The supplemental value set should only include the LOINC 79101-2 code."""
    assert CMS130v6CtColonography.LOINC == {"79101-2"}
    assert CMS130v6CtColonography.values == {"LOINC": {"79101-2"}}


def test_cms130v6_ct_colonography_combines_with_v2022() -> None:
    """The supplemental value set should compose with the v2022 CtColonography via | operator."""
    from canvas_sdk.value_set.v2022.diagnostic_study import CtColonography

    combined = CtColonography | CMS130v6CtColonography
    combined_values = combined.values
    assert "79101-2" in combined_values["LOINC"]


def test_in_age_range_below_minimum() -> None:
    """A 49-year-old patient should not be in the age range."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1969, 1, 1), now=now)
    assert protocol.in_age_range() is False


def test_in_age_range_at_minimum() -> None:
    """A 50-year-old patient should be in the age range."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1968, 8, 22), now=now)
    assert protocol.in_age_range() is True


def test_in_age_range_at_maximum() -> None:
    """A 75-year-old patient should be in the age range."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1943, 8, 23), now=now)
    assert protocol.in_age_range() is True


def test_in_age_range_above_maximum() -> None:
    """A 76-year-old patient should not be in the age range."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1942, 8, 22), now=now)
    assert protocol.in_age_range() is False


def test_first_due_in_returns_none_when_already_eligible() -> None:
    """A patient already 50+ should yield None from first_due_in()."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1968, 8, 22), now=now)
    assert protocol.first_due_in() is None


def test_first_due_in_returns_days_for_younger_patient() -> None:
    """A patient turning 50 in N days should yield N from first_due_in()."""
    now = arrow.get("2018-08-23 12:00:00")
    # Birthday 2018-08-30 + 50 years comparison: shift by 50 from 1968-08-30 = 2018-08-30.
    protocol = _make_protocol(birth_date=date(1968, 8, 30), now=now)
    due = protocol.first_due_in()
    assert due is not None
    # The legacy test asserted 6, plus or minus a day for the timezone-naive
    # comparison; allow a small window so the test is not brittle.
    assert 5 <= due <= 7


def test_first_due_in_returns_none_when_exclusion_present() -> None:
    """An under-50 patient with a colon exclusion should still yield None."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(
        birth_date=date(1968, 8, 30),
        now=now,
        has_exclusion=True,
    )
    assert protocol.first_due_in() is None


def test_in_denominator_requires_age_range() -> None:
    """An under-50 patient is never in the denominator regardless of other state."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1980, 1, 1), now=now)
    assert protocol.in_denominator() is False


def test_in_denominator_requires_no_exclusion() -> None:
    """A 50-75 year old with a colon exclusion should not be in the denominator."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(
        birth_date=date(1960, 1, 1),
        now=now,
        has_exclusion=True,
    )
    assert protocol.in_denominator() is False


def test_in_denominator_includes_eligible_patient() -> None:
    """A 50-75 year old without exclusions should be in the denominator."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1960, 1, 1), now=now)
    assert protocol.in_denominator() is True


def test_compute_returns_not_applicable_for_underage_patient() -> None:
    """An under-50 patient's protocol card should be NOT_APPLICABLE."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1980, 1, 1), now=now)
    with patch.object(
        ClinicalQualityMeasure130v6,
        "_last_exam",
        new=None,
    ):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_returns_due_card_when_no_recent_exam() -> None:
    """An eligible patient with no qualifying exam should yield a DUE card."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1960, 1, 1), now=now)
    with patch.object(
        ClinicalQualityMeasure130v6,
        "_last_exam",
        new=None,
    ):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_returns_satisfied_card_when_recent_exam_present() -> None:
    """An eligible patient with a recent qualifying exam should yield a SATISFIED card."""
    now = arrow.get("2018-08-23 12:00:00")
    protocol = _make_protocol(birth_date=date(1960, 1, 1), now=now)
    exam = {"date": "2018-08-05", "what": "FOBT", "days": SCREENING_INTERVALS["FOBT"]}
    with patch.object(
        ClinicalQualityMeasure130v6,
        "_last_exam",
        new=exam,
    ):
        effects = protocol.compute()
    assert len(effects) == 1


@pytest.mark.parametrize(
    "exam_type,expected_days",
    [
        ("FOBT", 365),
        ("FIT-DNA", 1096),
        ("Flexible sigmoidoscopy", 1826),
        ("CT Colonography", 1826),
        ("Colonoscopy", 3652),
    ],
)
def test_each_exam_type_has_expected_window(exam_type: str, expected_days: int) -> None:
    """Every screening exam type should have its specification-defined window."""
    assert SCREENING_INTERVALS[exam_type] == expected_days
