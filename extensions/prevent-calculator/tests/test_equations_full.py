"""Tests for the PREVENT full-model port (UACR / HbA1c / SDI extension)."""

from __future__ import annotations

from prevent_calculator.services.equations import (
    PreventInput,
    SEX_FEMALE,
    SEX_MALE,
    compute_prevent,
    compute_prevent_base,
)
from prevent_calculator.services.equations_full import (
    _hba1c_terms,
    _ln,
    _sdi_dummies,
    _uacr_term,
    compute_prevent_full,
    has_any_enhanced_input,
)


# -- encoding helpers -------------------------------------------------------


def test_sdi_dummies_reference_categories() -> None:
    assert _sdi_dummies(1) == (0, 0, 0)
    assert _sdi_dummies(3) == (0, 0, 0)
    assert _sdi_dummies(4) == (1, 0, 0)
    assert _sdi_dummies(6) == (1, 0, 0)
    assert _sdi_dummies(7) == (0, 1, 0)
    assert _sdi_dummies(10) == (0, 1, 0)


def test_sdi_dummies_missing_or_invalid() -> None:
    assert _sdi_dummies(None) == (0, 0, 1)
    assert _sdi_dummies("xyz") == (0, 0, 1)
    assert _sdi_dummies(0) == (0, 0, 1)
    assert _sdi_dummies(11) == (0, 0, 1)


def test_hba1c_split_by_diabetes_status() -> None:
    # diabetic path
    assert _hba1c_terms(7.0, 1) == (7.0 - 5.3, 0.0, 0)
    # non-diabetic path
    assert _hba1c_terms(6.0, 0) == (0.0, 6.0 - 5.3, 0)
    # missing
    assert _hba1c_terms(None, 1) == (0.0, 0.0, 1)
    assert _hba1c_terms("x", 0) == (0.0, 0.0, 1)


def test_uacr_term_uses_natural_log() -> None:
    val, missing = _uacr_term(10.0)
    assert missing == 0
    # ln(10) ≈ 2.302585
    assert abs(val - 2.302585) < 1e-4


def test_uacr_term_missing_for_invalid_inputs() -> None:
    assert _uacr_term(None) == (0.0, 1)
    assert _uacr_term(-5) == (0.0, 1)
    assert _uacr_term("abc") == (0.0, 1)


def test_ln_helper_matches_python_math_for_typical_uacr_range() -> None:
    import math

    for value in (0.1, 1.0, 10.0, 100.0, 1000.0, 25000.0):
        expected = math.log(value)
        assert abs(_ln(value) - expected) < 1e-9, value


def test_ln_helper_guards_against_non_finite_inputs() -> None:
    """Regression: ``_ln`` previously hung on ``float('inf')`` because the
    range-reduction loop kept halving an infinite value. NaN would have
    poisoned the artanh series. Both now return 0 instead of looping.
    """
    assert _ln(float("inf")) == 0.0
    assert _ln(float("-inf")) == 0.0
    assert _ln(float("nan")) == 0.0
    # And the existing non-positive guard still holds:
    assert _ln(0.0) == 0.0
    assert _ln(-1.0) == 0.0


# -- dispatch logic ---------------------------------------------------------


def _base_inputs(**overrides: float | int | None) -> PreventInput:
    """Return a complete PreventInput with optional field overrides."""
    defaults: dict = dict(
        sex=SEX_FEMALE,
        age=55,
        tc=200,
        hdl=60,
        sbp=120,
        dm=0,
        smoking=0,
        bmi=27,
        egfr=85,
        bptreat=0,
        statin=0,
    )
    defaults.update(overrides)
    return PreventInput(**defaults)


def test_has_any_enhanced_input_detects_each_predictor() -> None:
    assert has_any_enhanced_input(_base_inputs(uacr=15)) is True
    assert has_any_enhanced_input(_base_inputs(hba1c=5.7)) is True
    assert has_any_enhanced_input(_base_inputs(sdi_decile=4)) is True
    assert has_any_enhanced_input(_base_inputs()) is False


def test_compute_prevent_dispatches_to_full_when_uacr_provided() -> None:
    base_only = _base_inputs()
    with_uacr = _base_inputs(uacr=10)

    base_result = compute_prevent(base_only)
    enhanced_result = compute_prevent(with_uacr)

    # Base path matches compute_prevent_base
    assert base_result == compute_prevent_base(base_only)
    # Full path matches compute_prevent_full
    assert enhanced_result == compute_prevent_full(with_uacr)
    # And adding UACR should change the 10-yr CVD risk
    assert base_result.risk_10yr_cvd is not None
    assert enhanced_result.risk_10yr_cvd is not None
    assert abs(base_result.risk_10yr_cvd - enhanced_result.risk_10yr_cvd) > 1e-6


def test_full_model_runs_with_only_one_enhanced_predictor() -> None:
    """All three enhanced predictors are independently optional."""
    inputs = _base_inputs(hba1c=6.5)  # only HbA1c — UACR and SDI absent
    result = compute_prevent_full(inputs)
    assert result.risk_10yr_cvd is not None
    assert result.risk_10yr_hf is not None
    assert result.risk_30yr_cvd is not None


def test_full_model_male_diabetic_with_all_enhanced_inputs() -> None:
    """Sanity check that male path runs end-to-end with all three predictors."""
    inputs = _base_inputs(
        sex=SEX_MALE, age=58, dm=1, hba1c=8.2, uacr=120, sdi_decile=8
    )
    result = compute_prevent_full(inputs)
    # Diabetic + high UACR + high SDI should yield non-trivial 10-yr CVD risk
    assert result.risk_10yr_cvd is not None
    assert result.risk_10yr_cvd > 5.0
    # 30-yr scores still computed for age 58 (≤59)
    assert result.risk_30yr_cvd is not None


def test_full_model_skips_30yr_for_older_patients() -> None:
    inputs = _base_inputs(age=65, hba1c=6.0)
    result = compute_prevent_full(inputs)
    assert result.risk_30yr_cvd is None
    assert result.risk_30yr_ascvd is None
    assert result.risk_30yr_hf is None
    # 10-yr scores still computed
    assert result.risk_10yr_cvd is not None


def test_full_model_returns_none_when_common_inputs_invalid() -> None:
    """The shared age/SBP/eGFR gate still applies in the full model."""
    inputs = _base_inputs(age=25, hba1c=6.0)
    result = compute_prevent_full(inputs)
    assert result.risk_10yr_cvd is None
    assert result.risk_10yr_hf is None
