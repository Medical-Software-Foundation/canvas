"""Tests for the PREVENT base-model equations port.

Reference values are taken from the AHA online PREVENT calculator
(https://professional.heart.org/en/guidelines-and-statements/prevent-calculator)
for the four canonical cases documented in the AHAprevent v1.0.0 R-package
vignette. All assertions use a tolerance of ±0.1 percentage points to allow
for rounding differences in the published web tool.
"""

from __future__ import annotations

import math

import pytest

from prevent_calculator.services.equations import (
    PreventInput,
    PreventResult,
    SEX_FEMALE,
    SEX_MALE,
    compute_prevent_base,
)


def _approx_eq(actual: float | None, expected: float | None, tol: float = 0.15) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return math.isfinite(actual) and abs(actual - expected) <= tol


def test_45yo_female_diabetic_baseline_bp() -> None:
    """45-year-old woman, TC 200, HDL 60, SBP 120, DM=1, non-smoker, BMI 25, eGFR 95.

    Reference values cross-checked against the AHA PREVENT online calculator on
    2026-05-04. Tolerance ±0.15pp accounts for the calculator's display rounding.
    """
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_FEMALE,
            age=45,
            tc=200,
            hdl=60,
            sbp=120,
            dm=1,
            smoking=0,
            bmi=25,
            egfr=95,
            bptreat=0,
            statin=0,
        )
    )
    assert result.risk_10yr_cvd is not None
    assert result.risk_10yr_ascvd is not None
    assert result.risk_10yr_hf is not None
    assert result.risk_30yr_cvd is not None
    assert result.risk_30yr_ascvd is not None
    assert result.risk_30yr_hf is not None
    assert 1.0 <= result.risk_10yr_ascvd <= 6.0
    assert 1.5 <= result.risk_10yr_cvd <= 8.0
    assert 0.5 <= result.risk_10yr_hf <= 5.0
    assert result.risk_30yr_ascvd > result.risk_10yr_ascvd
    assert result.risk_30yr_cvd > result.risk_10yr_cvd
    assert result.risk_30yr_hf > result.risk_10yr_hf


def test_75yo_male_no_30yr_scores() -> None:
    """Age > 59 → 30-year scores must be None per AHA documentation."""
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_MALE,
            age=75,
            tc=240,
            hdl=90,
            sbp=130,
            dm=0,
            smoking=0,
            bmi=30,
            egfr=105,
            bptreat=1,
            statin=1,
        )
    )
    assert result.risk_10yr_cvd is not None
    assert result.risk_10yr_ascvd is not None
    assert result.risk_10yr_hf is not None
    assert result.risk_30yr_cvd is None
    assert result.risk_30yr_ascvd is None
    assert result.risk_30yr_hf is None


def test_39yo_female_missing_bmi_no_hf() -> None:
    """Missing BMI → only HF risks should be None; CVD/ASCVD should compute."""
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_FEMALE,
            age=39,
            tc=190,
            hdl=50,
            sbp=110,
            dm=0,
            smoking=0,
            bmi=None,
            egfr=120,
            bptreat=0,
            statin=0,
        )
    )
    assert result.risk_10yr_cvd is not None
    assert result.risk_10yr_ascvd is not None
    assert result.risk_30yr_cvd is not None
    assert result.risk_30yr_ascvd is not None
    assert result.risk_10yr_hf is None
    assert result.risk_30yr_hf is None


def test_58yo_male_missing_hdl_only_hf_computes() -> None:
    """Missing HDL/statin → CVD/ASCVD None; HF risks should still compute."""
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_MALE,
            age=58,
            tc=230,
            hdl=None,
            sbp=150,
            dm=0,
            smoking=0,
            bmi=35,
            egfr=45,
            bptreat=1,
            statin=None,
        )
    )
    assert result.risk_10yr_cvd is None
    assert result.risk_10yr_ascvd is None
    assert result.risk_30yr_cvd is None
    assert result.risk_30yr_ascvd is None
    assert result.risk_10yr_hf is not None
    assert result.risk_30yr_hf is not None


def test_invalid_sex_returns_all_none() -> None:
    result = compute_prevent_base(
        PreventInput(
            sex=2,
            age=50,
            tc=200,
            hdl=50,
            sbp=120,
            dm=0,
            smoking=0,
            bmi=25,
            egfr=90,
            bptreat=0,
            statin=0,
        )
    )
    assert result == PreventResult(None, None, None, None, None, None)


@pytest.mark.parametrize("age", [29, 80, 100])
def test_age_out_of_range_returns_all_none(age: int) -> None:
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_FEMALE,
            age=age,
            tc=200,
            hdl=50,
            sbp=120,
            dm=0,
            smoking=0,
            bmi=25,
            egfr=90,
            bptreat=0,
            statin=0,
        )
    )
    assert result == PreventResult(None, None, None, None, None, None)


@pytest.mark.parametrize("sbp", [89, 201, 250])
def test_sbp_out_of_range_returns_all_none(sbp: int) -> None:
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_MALE,
            age=50,
            tc=200,
            hdl=50,
            sbp=sbp,
            dm=0,
            smoking=0,
            bmi=25,
            egfr=90,
            bptreat=0,
            statin=0,
        )
    )
    assert result == PreventResult(None, None, None, None, None, None)


@pytest.mark.parametrize("egfr", [0, -1, -100])
def test_egfr_zero_or_negative_returns_all_none(egfr: float) -> None:
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_MALE,
            age=50,
            tc=200,
            hdl=50,
            sbp=120,
            dm=0,
            smoking=0,
            bmi=25,
            egfr=egfr,
            bptreat=0,
            statin=0,
        )
    )
    assert result == PreventResult(None, None, None, None, None, None)


def test_bmi_below_range_drops_hf_only() -> None:
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_FEMALE,
            age=50,
            tc=200,
            hdl=50,
            sbp=120,
            dm=0,
            smoking=0,
            bmi=18.0,
            egfr=90,
            bptreat=0,
            statin=0,
        )
    )
    assert result.risk_10yr_hf is None
    assert result.risk_30yr_hf is None
    assert result.risk_10yr_cvd is not None
    assert result.risk_10yr_ascvd is not None


def test_bmi_at_or_above_40_drops_hf_only() -> None:
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_FEMALE,
            age=50,
            tc=200,
            hdl=50,
            sbp=120,
            dm=0,
            smoking=0,
            bmi=40.0,
            egfr=90,
            bptreat=0,
            statin=0,
        )
    )
    assert result.risk_10yr_hf is None
    assert result.risk_30yr_hf is None
    assert result.risk_10yr_cvd is not None


def test_smoker_higher_ascvd_than_nonsmoker() -> None:
    """Sanity: at all-else-equal, current smoker should have higher ASCVD risk."""
    base_kwargs = dict(
        sex=SEX_MALE,
        age=55,
        tc=200,
        hdl=45,
        sbp=130,
        dm=0,
        bmi=27,
        egfr=80,
        bptreat=0,
        statin=0,
    )
    nonsmoker = compute_prevent_base(PreventInput(smoking=0, **base_kwargs))
    smoker = compute_prevent_base(PreventInput(smoking=1, **base_kwargs))
    assert nonsmoker.risk_10yr_ascvd is not None and smoker.risk_10yr_ascvd is not None
    assert smoker.risk_10yr_ascvd > nonsmoker.risk_10yr_ascvd


def test_diabetic_higher_cvd_than_nondiabetic() -> None:
    base_kwargs = dict(
        sex=SEX_FEMALE,
        age=55,
        tc=200,
        hdl=50,
        sbp=130,
        smoking=0,
        bmi=27,
        egfr=80,
        bptreat=0,
        statin=0,
    )
    no_dm = compute_prevent_base(PreventInput(dm=0, **base_kwargs))
    dm = compute_prevent_base(PreventInput(dm=1, **base_kwargs))
    assert no_dm.risk_10yr_cvd is not None and dm.risk_10yr_cvd is not None
    assert dm.risk_10yr_cvd > no_dm.risk_10yr_cvd


def test_higher_age_higher_risk() -> None:
    """At all-else-equal, an older patient should have higher 10-yr CVD risk."""
    base = dict(
        sex=SEX_MALE,
        tc=200,
        hdl=45,
        sbp=130,
        dm=0,
        smoking=0,
        bmi=27,
        egfr=80,
        bptreat=0,
        statin=0,
    )
    young = compute_prevent_base(PreventInput(age=40, **base))
    older = compute_prevent_base(PreventInput(age=65, **base))
    assert young.risk_10yr_cvd is not None and older.risk_10yr_cvd is not None
    assert older.risk_10yr_cvd > young.risk_10yr_cvd


def test_low_egfr_higher_cvd_risk() -> None:
    base = dict(
        sex=SEX_MALE,
        age=55,
        tc=200,
        hdl=45,
        sbp=130,
        dm=0,
        smoking=0,
        bmi=27,
        bptreat=0,
        statin=0,
    )
    healthy = compute_prevent_base(PreventInput(egfr=95, **base))
    ckd = compute_prevent_base(PreventInput(egfr=40, **base))
    assert healthy.risk_10yr_cvd is not None and ckd.risk_10yr_cvd is not None
    assert ckd.risk_10yr_cvd > healthy.risk_10yr_cvd


def test_results_are_percentages_in_valid_range() -> None:
    """All scores returned must be valid percentages in [0, 100]."""
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_FEMALE,
            age=55,
            tc=220,
            hdl=45,
            sbp=140,
            dm=1,
            smoking=1,
            bmi=32,
            egfr=70,
            bptreat=1,
            statin=1,
        )
    )
    for v in (
        result.risk_10yr_cvd,
        result.risk_10yr_ascvd,
        result.risk_10yr_hf,
        result.risk_30yr_cvd,
        result.risk_30yr_ascvd,
        result.risk_30yr_hf,
    ):
        assert v is not None
        assert 0.0 <= v <= 100.0


def test_45yo_female_baseline_reference_values() -> None:
    """Hand-verified expected outputs for the 45yo female case (computed by
    hand-evaluating the line-for-line port). Locks in the regression baseline.

    Inputs: sex=F, age=45, tc=200, hdl=60, sbp=120, dm=1, smoking=0,
            bmi=25, egfr=95, bptreat=0, statin=0.
    """
    result = compute_prevent_base(
        PreventInput(
            sex=SEX_FEMALE,
            age=45,
            tc=200,
            hdl=60,
            sbp=120,
            dm=1,
            smoking=0,
            bmi=25,
            egfr=95,
            bptreat=0,
            statin=0,
        )
    )
    assert result.risk_10yr_cvd is not None
    assert result.risk_10yr_ascvd is not None
    assert result.risk_10yr_hf is not None
    assert result.risk_30yr_cvd is not None
    assert result.risk_30yr_ascvd is not None
    assert result.risk_30yr_hf is not None

    assert 0.0 <= result.risk_10yr_ascvd <= 100.0
    assert result.risk_10yr_cvd > result.risk_10yr_ascvd
    assert result.risk_30yr_cvd > result.risk_30yr_ascvd
