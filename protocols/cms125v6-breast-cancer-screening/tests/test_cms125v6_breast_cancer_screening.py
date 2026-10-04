"""Unit tests for the CMS125v6 Breast Cancer Screening protocol.

These tests exercise the pure-logic methods by injecting fake patient,
conditions, and imaging reports through the constructor. They do not touch
the database; that integration path is covered separately when the plugin
runs inside the plugin runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import arrow
import pytest

from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.patient import SexAtBirth

from protocols.cms125v6_breast_cancer_screening import (
    CMS125v6Tomography,
    ClinicalQualityMeasure125v6,
    UnilateralMastectomy,
)


SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
HCPCS = "http://www.cms.gov/medicare/coding/medhcpcsgeninfo"


@dataclass
class FakePatient:
    """A minimal stand-in for ``canvas_sdk.v1.data.patient.Patient``.

    Includes only the attributes the protocol reads.
    """

    id: str = "patient-1"
    first_name: str = "Jane"
    sex_at_birth: str = SexAtBirth.FEMALE
    birth_date: date | None = None

    def __post_init__(self) -> None:
        if self.birth_date is None:
            self.birth_date = date(1960, 1, 1)

    def age_at(self, time: arrow.Arrow) -> float:
        """Return the patient's age (fractional years) at ``time``."""
        birth = arrow.get(self.birth_date)
        if birth.date() >= time.date():
            return 0.0
        years = time.datetime.year - birth.datetime.year
        if time.datetime.month < birth.datetime.month or (
            time.datetime.month == birth.datetime.month
            and time.datetime.day < birth.datetime.day
        ):
            years -= 1
        current_year = birth.shift(years=years)
        next_year = birth.shift(years=years + 1)
        return years + (time.date() - current_year.date()) / (
            next_year.date() - current_year.date()
        )


def make_condition(system: str, code: str, onset: str | None = "2018-07-23") -> dict[str, Any]:
    """Build a fake condition record with one coding and an onset date."""
    return {
        "id": code,
        "codings": [{"system": system, "code": code}],
        "onset_date": date.fromisoformat(onset) if onset else None,
    }


def make_imaging_report(system: str, code: str, original_date: str) -> dict[str, Any]:
    """Build a fake imaging report with one coding and an original date."""
    return {
        "codings": [{"system": system, "code": code}],
        "originalDate": original_date,
    }


def build_protocol(
    *,
    patient: FakePatient | None = None,
    timeframe: Timeframe | None = None,
    now: arrow.Arrow | None = None,
    conditions: list[dict[str, Any]] | None = None,
    imaging_reports: list[dict[str, Any]] | None = None,
) -> ClinicalQualityMeasure125v6:
    """Construct a protocol instance with sensible test defaults injected."""
    if patient is None:
        patient = FakePatient()
    if timeframe is None:
        timeframe = Timeframe(
            start=arrow.get("2017-08-23 13:24:56"),
            end=arrow.get("2018-08-23 13:24:56"),
        )
    return ClinicalQualityMeasure125v6(
        patient=patient,
        timeframe=timeframe,
        now=now,
        conditions=conditions or [],
        imaging_reports=imaging_reports or [],
    )


# --- metadata ----------------------------------------------------------------


def test_description() -> None:
    """The class description matches the legacy CMS125v6 description."""
    expected = (
        "Women 50-74 years of age who have not had a mammogram to screen for "
        "breast cancer within the last 27 months."
    )
    assert ClinicalQualityMeasure125v6.Meta.description == expected


def test_information_url() -> None:
    """The information URL points at the CMS125v6 spec on ecqi.healthit.gov."""
    assert (
        ClinicalQualityMeasure125v6.Meta.information
        == "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS125v6.html"
    )


def test_identifier() -> None:
    """The protocol declares the CMS125v6 identifier."""
    assert ClinicalQualityMeasure125v6.Meta.identifiers == ["CMS125v6"]


def test_default_display_interval() -> None:
    """Default display interval rounds 27 months to ``2y + 3m`` of days."""
    assert ClinicalQualityMeasure125v6.Meta.default_display_interval_in_days == (
        365 * 2 + 3 * 30
    )


def test_responds_to_event_types() -> None:
    """The protocol subscribes to the patient/condition/imaging/billing event types."""
    responds_to = set(ClinicalQualityMeasure125v6.RESPONDS_TO)
    expected = {
        "CONDITION_ASSESSED",
        "CONDITION_CREATED",
        "CONDITION_RESOLVED",
        "CONDITION_UPDATED",
        "IMAGING_REPORT_CREATED",
        "IMAGING_REPORT_UPDATED",
        "PATIENT_CREATED",
        "PATIENT_UPDATED",
        "BILLING_LINE_ITEM_CREATED",
        "BILLING_LINE_ITEM_UPDATED",
    }
    assert expected.issubset(responds_to)


# --- demographics ------------------------------------------------------------


@pytest.mark.parametrize(
    "sex,expected",
    [
        (SexAtBirth.FEMALE, True),
        (SexAtBirth.MALE, False),
        (SexAtBirth.OTHER, False),
        (SexAtBirth.UNKNOWN, False),
    ],
)
def test_is_female(sex: str, expected: bool) -> None:
    """``is_female`` reflects the patient's sex_at_birth flag."""
    protocol = build_protocol(patient=FakePatient(sex_at_birth=sex))
    assert protocol.is_female is expected


# --- had_mastectomy ----------------------------------------------------------


def test_had_mastectomy_no_evidence() -> None:
    """A patient with no relevant conditions does not have a mastectomy."""
    protocol = build_protocol(conditions=[])
    assert protocol.had_mastectomy() is False


def test_had_mastectomy_bilateral() -> None:
    """One bilateral-mastectomy coding triggers the exclusion."""
    # SNOMED 27865001 is in BilateralMastectomy.
    conditions = [make_condition(SNOMED, "27865001")]
    protocol = build_protocol(conditions=conditions)
    assert protocol.had_mastectomy() is True


def test_had_mastectomy_single_unilateral() -> None:
    """A single unilateral mastectomy alone does not trigger the exclusion."""
    # SNOMED 172043006 is in UnilateralMastectomy.
    conditions = [make_condition(SNOMED, "172043006")]
    protocol = build_protocol(conditions=conditions)
    assert protocol.had_mastectomy() is False


def test_had_mastectomy_two_unilateral() -> None:
    """Two distinct unilateral-mastectomy rows trigger the exclusion."""
    conditions = [
        {**make_condition(SNOMED, "172043006"), "id": "u1"},
        {**make_condition(SNOMED, "172043006"), "id": "u2"},
    ]
    protocol = build_protocol(conditions=conditions)
    assert protocol.had_mastectomy() is True


def test_had_mastectomy_unilateral_plus_status_post_right() -> None:
    """One unilateral plus a Status-Post-Right diagnosis triggers the exclusion."""
    # SNOMED 429242008 is in StatusPostRightMastectomy.
    conditions = [
        make_condition(SNOMED, "172043006"),
        make_condition(SNOMED, "429242008"),
    ]
    protocol = build_protocol(conditions=conditions)
    assert protocol.had_mastectomy() is True


def test_had_mastectomy_unilateral_plus_status_post_left() -> None:
    """One unilateral plus a Status-Post-Left diagnosis triggers the exclusion."""
    # SNOMED 429009003 is in StatusPostLeftMastectomy.
    conditions = [
        make_condition(SNOMED, "172043006"),
        make_condition(SNOMED, "429009003"),
    ]
    protocol = build_protocol(conditions=conditions)
    assert protocol.had_mastectomy() is True


def test_had_mastectomy_status_post_alone_does_not_trigger() -> None:
    """A Status-Post diagnosis without a unilateral mastectomy is not enough."""
    conditions = [make_condition(SNOMED, "429242008")]
    protocol = build_protocol(conditions=conditions)
    assert protocol.had_mastectomy() is False


# --- first_due_in ------------------------------------------------------------


def test_first_due_in_older_than_start_age() -> None:
    """``first_due_in`` is ``None`` once the patient is already eligible."""
    protocol = build_protocol(patient=FakePatient(birth_date=date(1967, 8, 22)))
    assert protocol.first_due_in() is None


def test_first_due_in_younger_than_start_age() -> None:
    """``first_due_in`` returns the number of days until the patient turns 51.

    Matches the legacy CMS125v6 expectation: timeframe.end is ``2018-08-23 13:24:56``,
    birthday is ``1967-08-30`` → patient turns 51 on ``2018-08-30 00:00:00`` → ``6``
    days remaining once the partial day of timeframe.end is floored away.
    """
    protocol = build_protocol(patient=FakePatient(birth_date=date(1967, 8, 30)))
    assert protocol.first_due_in() == 6


def test_first_due_in_with_mastectomy_returns_none() -> None:
    """A patient excluded for mastectomy never has a 'first due' date."""
    patient = FakePatient(birth_date=date(1967, 8, 30))
    conditions = [make_condition(SNOMED, "27865001")]  # bilateral
    protocol = build_protocol(patient=patient, conditions=conditions)
    assert protocol.first_due_in() is None


# --- in_initial_population ---------------------------------------------------


def test_in_initial_population_woman_in_range() -> None:
    """A woman aged 51-74 at timeframe.end is in the initial population."""
    protocol = build_protocol()
    assert protocol.in_initial_population() is True


@pytest.mark.parametrize("sex", [SexAtBirth.MALE, SexAtBirth.OTHER, SexAtBirth.UNKNOWN])
def test_in_initial_population_non_female(sex: str) -> None:
    """Non-female patients are not in the initial population."""
    protocol = build_protocol(patient=FakePatient(sex_at_birth=sex))
    assert protocol.in_initial_population() is False


def test_in_initial_population_younger_than_51() -> None:
    """A woman younger than 51 at timeframe.end is excluded."""
    timeframe = Timeframe(
        start=arrow.get("2017-08-23 13:24:56"),
        end=arrow.get("2018-08-23 13:24:56"),
    )
    # birthDate = end shifted -51 years +1 day = still 50 at end.
    patient = FakePatient(birth_date=date(1967, 8, 24))
    protocol = build_protocol(patient=patient, timeframe=timeframe)
    assert protocol.in_initial_population() is False


def test_in_initial_population_older_than_74() -> None:
    """A woman older than 74 at timeframe.end is excluded."""
    timeframe = Timeframe(
        start=arrow.get("2017-08-23 13:24:56"),
        end=arrow.get("2018-08-23 13:24:56"),
    )
    patient = FakePatient(birth_date=date(1944, 8, 22))  # >74 at end
    protocol = build_protocol(patient=patient, timeframe=timeframe)
    assert protocol.in_initial_population() is False


# --- in_denominator ----------------------------------------------------------


def test_in_denominator_woman_no_mastectomy() -> None:
    """A woman in the initial population without exclusions is in the denominator."""
    protocol = build_protocol()
    assert protocol.in_denominator() is True


def test_in_denominator_with_bilateral_mastectomy() -> None:
    """A bilateral-mastectomy patient is excluded from the denominator."""
    conditions = [make_condition(SNOMED, "27865001")]
    protocol = build_protocol(conditions=conditions)
    assert protocol.in_denominator() is False


# --- in_numerator ------------------------------------------------------------


def test_in_numerator_no_mammogram() -> None:
    """A patient with no mammograms is not in the numerator."""
    protocol = build_protocol()
    assert protocol.in_numerator() is False


def test_in_numerator_recent_mammogram() -> None:
    """A mammogram inside the measurement period puts the patient in the numerator."""
    reports = [make_imaging_report(LOINC, "24606-6", "2018-07-30")]
    protocol = build_protocol(imaging_reports=reports)
    assert protocol.in_numerator() is True
    assert protocol._on_date == arrow.get("2018-07-30")


def test_in_numerator_mammogram_within_15_month_lookback() -> None:
    """A mammogram up to 15 months before the period start counts."""
    # Start of timeframe: 2017-08-23. 15 months before = 2016-05-23.
    reports = [make_imaging_report(LOINC, "24606-6", "2016-06-01")]
    protocol = build_protocol(imaging_reports=reports)
    assert protocol.in_numerator() is True


def test_in_numerator_mammogram_too_old() -> None:
    """A mammogram older than 15 months before the period start does not count."""
    # 15 months before 2017-08-23 is 2016-05-23. Anything older is too old.
    reports = [make_imaging_report(LOINC, "24606-6", "2016-05-22")]
    protocol = build_protocol(imaging_reports=reports)
    assert protocol.in_numerator() is False


def test_in_numerator_tomography_code_counts() -> None:
    """The CMS125v6 tomography LOINC (72142-3) also satisfies the numerator."""
    reports = [make_imaging_report(LOINC, "72142-3", "2018-07-30")]
    protocol = build_protocol(imaging_reports=reports)
    assert protocol.in_numerator() is True


# --- compute -----------------------------------------------------------------


def test_compute_due() -> None:
    """A denominator patient with no mammogram gets a DUE protocol card."""
    now = arrow.get("2018-08-23 13:24:56")
    protocol = build_protocol(now=now)
    effects = protocol.compute()
    assert len(effects) == 1


def test_compute_satisfied() -> None:
    """A denominator patient with a recent mammogram gets a SATISFIED protocol card."""
    now = arrow.get("2018-08-23 13:24:56")
    reports = [make_imaging_report(LOINC, "24606-6", "2018-07-30")]
    protocol = build_protocol(now=now, imaging_reports=reports)
    effects = protocol.compute()
    assert len(effects) == 1
    # The on-date was recorded during in_numerator().
    assert protocol.in_numerator() is True


def test_compute_not_applicable_for_mastectomy_patient() -> None:
    """A mastectomy patient gets a NOT_APPLICABLE protocol card."""
    now = arrow.get("2018-08-23 13:24:56")
    conditions = [make_condition(SNOMED, "27865001")]
    protocol = build_protocol(now=now, conditions=conditions)
    effects = protocol.compute()
    assert len(effects) == 1


# --- value set sanity --------------------------------------------------------


def test_unilateral_mastectomy_value_set_contains_legacy_codes() -> None:
    """The inlined UnilateralMastectomy value set keeps the legacy SNOMED list."""
    assert "172043006" in UnilateralMastectomy.SNOMEDCT
    assert "70183006" in UnilateralMastectomy.SNOMEDCT


def test_cms125v6_tomography_value_set() -> None:
    """The inlined CMS125v6Tomography value set carries LOINC 72142-3."""
    assert CMS125v6Tomography.LOINC == {"72142-3"}
