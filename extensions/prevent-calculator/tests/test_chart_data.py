"""Tests for the chart-data fetcher.

Uses mock SDK querysets so the helpers can be exercised without a Canvas
database. Real-database integration is verified during UAT.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from prevent_calculator.services import chart_data
from prevent_calculator.services.chart_data import (
    ChartPrefill,
    ChartValue,
    _matches_any,
    _resolve_active_medication_flag,
    _resolve_age,
    _resolve_diabetes,
    _resolve_sex,
    _resolve_smoking,
    _resolve_systolic_bp,
    _to_iso,
    _try_float,
    chart_prefill_to_dict,
    chart_value_to_dict,
    fetch_chart_prefill,
)
from prevent_calculator.services.loinc import LOINC_TOTAL_CHOLESTEROL


# -- pure helpers -----------------------------------------------------------


def test_to_iso_handles_datetime_date_and_none() -> None:
    assert _to_iso(None) is None
    assert _to_iso(dt.date(2026, 1, 15)) == "2026-01-15"
    assert _to_iso(dt.datetime(2026, 1, 15, 12, 30)) == "2026-01-15"
    # Pass-through for unexpected types
    assert _to_iso("custom-string") == "custom-string"


def test_try_float_parses_strings_and_skips_garbage() -> None:
    assert _try_float(None) is None
    assert _try_float("") is None
    assert _try_float("abc") is None
    assert _try_float("12.5") == 12.5
    assert _try_float(7) == 7.0
    assert _try_float(7.5) == 7.5


def test_matches_any_lowercases_and_substrings() -> None:
    assert _matches_any("Take Atorvastatin 10mg", ("statin", "lisinopril"))
    assert _matches_any("Lisinopril", ("ace inhibitor", "lisinopril"))
    assert not _matches_any("Aspirin", ("statin",))
    assert not _matches_any("", ("statin",))


# -- Patient resolvers (no DB needed beyond stub) ---------------------------


def test_resolve_sex_male_female_unknown() -> None:
    male = SimpleNamespace(sex_at_birth="M")
    female = SimpleNamespace(sex_at_birth="F")
    other = SimpleNamespace(sex_at_birth="O")
    blank = SimpleNamespace(sex_at_birth="")

    assert _resolve_sex(male) is not None and _resolve_sex(male).value == 0  # type: ignore[union-attr]
    assert _resolve_sex(female) is not None and _resolve_sex(female).value == 1  # type: ignore[union-attr]
    assert _resolve_sex(other) is None
    assert _resolve_sex(blank) is None


def test_resolve_age_uses_age_at_when_birth_date_set() -> None:
    patient = MagicMock()
    patient.birth_date = dt.date(1970, 1, 1)
    patient.age_at.return_value = 56.0
    out = _resolve_age(patient)
    assert out is not None
    assert out.value == 56.0


def test_resolve_age_returns_none_without_birth_date() -> None:
    patient = SimpleNamespace(birth_date=None)
    assert _resolve_age(patient) is None


# -- Observation resolvers --------------------------------------------------


def _stub_observation(
    value: str, effective: dt.datetime | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        value=value,
        effective_datetime=effective or dt.datetime(2026, 3, 10, 9, 0),
    )


def test_resolve_systolic_bp_parses_slash_value() -> None:
    obs = _stub_observation("128/82")
    with patch.object(chart_data, "_latest_observation_by_name", return_value=obs):
        out = _resolve_systolic_bp("p1")
    assert out is not None
    assert out.value == 128.0
    assert out.clinical_date == "2026-03-10"


def test_resolve_systolic_bp_none_when_absent() -> None:
    with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
        assert _resolve_systolic_bp("p1") is None


def test_resolve_systolic_bp_none_when_value_unparsable() -> None:
    obs = _stub_observation("not-a-number")
    with patch.object(chart_data, "_latest_observation_by_name", return_value=obs):
        assert _resolve_systolic_bp("p1") is None


def test_resolve_diabetes_finds_e11_condition_active() -> None:
    coding_e11 = SimpleNamespace(code="E11.9")
    coding_other = SimpleNamespace(code="I10")
    condition = SimpleNamespace(
        codings=SimpleNamespace(all=lambda: [coding_e11]),
        onset_date=dt.date(2024, 7, 1),
    )
    nondm_condition = SimpleNamespace(
        codings=SimpleNamespace(all=lambda: [coding_other]),
        onset_date=dt.date(2025, 1, 1),
    )
    qs = MagicMock()
    qs.active.return_value.filter.return_value.prefetch_related.return_value.order_by.return_value = [
        nondm_condition,
        condition,
    ]
    with patch.object(chart_data.Condition, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = _resolve_diabetes("p1")
    assert out is not None
    assert out.value == 1
    assert out.clinical_date == "2024-07-01"


def test_resolve_diabetes_defaults_to_zero_with_no_match() -> None:
    qs = MagicMock()
    qs.active.return_value.filter.return_value.prefetch_related.return_value.order_by.return_value = []
    with patch.object(chart_data.Condition, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = _resolve_diabetes("p1")
    assert out is not None
    assert out.value == 0


def test_resolve_smoking_uses_value_codings() -> None:
    obs = SimpleNamespace(
        value_codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(code="449868002")]
        ),
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = _resolve_smoking("p1")
    assert out is not None
    assert out.value == 1
    assert out.clinical_date == "2026-04-01"


def test_resolve_smoking_returns_zero_when_no_current_code() -> None:
    obs = SimpleNamespace(
        value_codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(code="266919005")]  # never smoker
        ),
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = _resolve_smoking("p1")
    assert out is not None
    assert out.value == 0


def test_resolve_smoking_none_when_no_observation() -> None:
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        assert _resolve_smoking("p1") is None


# -- Medication resolvers ---------------------------------------------------


def _stub_medication(name: str, start: dt.datetime | None = None) -> SimpleNamespace:
    coding = SimpleNamespace(display=name)
    return SimpleNamespace(
        clinical_quantity_description="",
        codings=SimpleNamespace(all=lambda: [coding]),
        start_date=start or dt.datetime(2025, 6, 1),
    )


def test_resolve_active_medication_flag_matches_hint() -> None:
    statin = _stub_medication("Atorvastatin 20 MG Oral Tablet")
    aspirin = _stub_medication("Aspirin 81 MG Oral Tablet")
    qs = MagicMock()
    qs.active.return_value.prefetch_related.return_value = [aspirin, statin]
    with patch.object(chart_data.Medication, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = _resolve_active_medication_flag("p1", ("atorvastatin", "statin"))
    assert out.value == 1
    assert out.clinical_date == "2025-06-01"


def test_resolve_active_medication_flag_defaults_to_zero() -> None:
    qs = MagicMock()
    qs.active.return_value.prefetch_related.return_value = []
    with patch.object(chart_data.Medication, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = _resolve_active_medication_flag("p1", ("statin",))
    assert out.value == 0


# -- chart_value_to_dict / chart_prefill_to_dict ---------------------------


def test_chart_value_to_dict_handles_none_and_value() -> None:
    assert chart_value_to_dict(None) is None
    cv = ChartValue(value=42, clinical_date="2026-01-01")
    assert chart_value_to_dict(cv) == {
        "value": 42,
        "clinical_date": "2026-01-01",
        "source": "observation",
    }


def test_chart_prefill_to_dict_includes_all_fields() -> None:
    cv = ChartValue(value=1, clinical_date="2026-01-01")
    prefill = ChartPrefill(
        sex=cv, age=None, total_cholesterol=cv, hdl_cholesterol=None,
        systolic_bp=cv, bmi=None, egfr=cv, diabetes=cv, smoking=None,
        bp_treatment=cv, statin=None,
    )
    out = chart_prefill_to_dict(prefill)
    assert set(out.keys()) == {
        "sex", "age", "total_cholesterol", "hdl_cholesterol",
        "systolic_bp", "bmi", "egfr", "diabetes", "smoking",
        "bp_treatment", "statin",
        "hba1c", "uacr",
    }
    assert out["sex"] == {
        "value": 1,
        "clinical_date": "2026-01-01",
        "source": "observation",
    }
    assert out["age"] is None


# -- fetch_chart_prefill orchestration --------------------------------------


def test_fetch_chart_prefill_aggregates_resolvers() -> None:
    patient = SimpleNamespace(sex_at_birth="F", birth_date=dt.date(1980, 5, 1))
    patient_objects = MagicMock()
    patient_objects.get.return_value = patient

    cv = ChartValue(value=1, clinical_date="2026-01-01")

    def stub_resolver(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return cv

    fetch_loinc_mock = MagicMock(return_value={"sentinel-loinc-map": True})
    fetch_meds_mock = MagicMock(return_value=["sentinel-med-list"])
    match_meds_mock = MagicMock(return_value=cv)

    with (
        patch.object(chart_data.Patient, "objects", patient_objects),
        patch.object(chart_data, "_fetch_latest_observation_by_loinc_set", fetch_loinc_mock),
        patch.object(chart_data, "_fetch_active_medications", fetch_meds_mock),
        patch.object(chart_data, "_match_medication_by_hints", match_meds_mock),
        patch.object(chart_data, "_resolve_age", return_value=cv),
        patch.object(chart_data, "_resolve_total_cholesterol", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_hdl", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_systolic_bp", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_bmi", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_egfr", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_diabetes", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_smoking", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_hba1c", side_effect=stub_resolver),
        patch.object(chart_data, "_resolve_uacr", side_effect=stub_resolver),
    ):
        out = fetch_chart_prefill("patient-x")

    assert isinstance(out, ChartPrefill)
    assert out.sex is not None and out.sex.value == 1
    assert out.total_cholesterol is cv
    patient_objects.get.assert_called_once_with(id="patient-x")
    # The batched fetchers fire exactly once each (rather than once per
    # resolver) — this is the load-reduction the database-performance
    # review locked in.
    fetch_loinc_mock.assert_called_once_with("patient-x", chart_data._BATCHED_LOINC_CODES)
    fetch_meds_mock.assert_called_once_with("patient-x")
    # BP-treatment and statin matching share the materialised med list
    # rather than re-running ``Medication.objects.for_patient(...).active()``.
    assert match_meds_mock.call_count == 2
    bp_call_args, _ = match_meds_mock.call_args_list[0]
    statin_call_args, _ = match_meds_mock.call_args_list[1]
    assert bp_call_args[0] == ["sentinel-med-list"]
    assert statin_call_args[0] == ["sentinel-med-list"]


# -- _latest_observation_by_loinc / _name (queryset shape coverage) --------


def test_latest_observation_by_loinc_calls_filter_chain() -> None:
    qs = MagicMock()
    qs.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = "obs"
    with patch.object(chart_data.Observation, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = chart_data._latest_observation_by_loinc("p1", (LOINC_TOTAL_CHOLESTEROL,))
    assert out == "obs"
    qs.filter.assert_called_once()
    args, kwargs = qs.filter.call_args
    assert kwargs == {
        "codings__system": "http://loinc.org",
        "codings__code__in": (LOINC_TOTAL_CHOLESTEROL,),
    }


def test_latest_observation_by_name_calls_filter_chain() -> None:
    qs = MagicMock()
    qs.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = "obs"
    with patch.object(chart_data.Observation, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = chart_data._latest_observation_by_name("p1", "blood_pressure")
    assert out == "obs"
    qs.filter.assert_called_once_with(name="blood_pressure")


# -- LOINC-keyed resolvers (TC / HDL / BMI / eGFR) -------------------------


def test_resolve_total_cholesterol_returns_value_when_obs_present() -> None:
    obs = _stub_observation("210")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = chart_data._resolve_total_cholesterol("p1")
    assert out is not None and out.value == 210.0


def test_resolve_total_cholesterol_none_when_obs_missing() -> None:
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        assert chart_data._resolve_total_cholesterol("p1") is None


def test_resolve_total_cholesterol_none_when_value_unparsable() -> None:
    obs = _stub_observation("invalid")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        assert chart_data._resolve_total_cholesterol("p1") is None


def test_resolve_hdl_returns_value() -> None:
    obs = _stub_observation("55")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = chart_data._resolve_hdl("p1")
    assert out is not None and out.value == 55.0


def test_resolve_hdl_none_when_missing() -> None:
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        assert chart_data._resolve_hdl("p1") is None


def test_resolve_bmi_computes_from_height_and_weight() -> None:
    """Canvas stores height (inches) and weight (oz) as observations; BMI is
    derived rather than read directly. 70 in × 2880 oz ≈ 25.8 BMI."""
    height_obs = SimpleNamespace(
        value="70",
        units="",  # defaults to inches per Canvas vital-sign convention
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    weight_obs = SimpleNamespace(
        value="2880",  # 180 lb in oz
        units="",
        effective_datetime=dt.datetime(2026, 4, 5),
    )
    with patch.object(chart_data, "_latest_observation_by_loinc") as loinc_mock:
        loinc_mock.side_effect = [height_obs, weight_obs]
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            out = chart_data._resolve_bmi("p1")
    assert out is not None
    assert 25.0 < out.value < 27.0


def test_resolve_bmi_falls_back_to_direct_bmi_observation() -> None:
    """When height/weight aren't available, fall back to a direct BMI
    observation (LOINC 39156-5 or name="body_mass_index")."""
    bmi_obs = _stub_observation("28.4")
    with patch.object(chart_data, "_latest_observation_by_loinc") as loinc_mock:
        # height lookup → None, weight lookup → None, then direct BMI lookup → bmi_obs
        loinc_mock.side_effect = [None, None, bmi_obs]
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            out = chart_data._resolve_bmi("p1")
    assert out is not None and out.value == 28.4


def test_resolve_bmi_none_when_no_data() -> None:
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            assert chart_data._resolve_bmi("p1") is None


def test_resolve_bmi_none_when_direct_bmi_value_unparsable() -> None:
    """Unparsable values in the direct-BMI fallback path return None."""
    obs = _stub_observation("garbage")
    with patch.object(chart_data, "_latest_observation_by_loinc") as loinc_mock:
        loinc_mock.side_effect = [None, None, obs]
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            assert chart_data._resolve_bmi("p1") is None


def test_resolve_bmi_uses_batched_loinc_map_in_production_path() -> None:
    """In production ``fetch_chart_prefill`` passes a pre-fetched
    ``loinc_map`` dict to every resolver so the per-LOINC fallback
    queries don't fire. Without this test the integration between
    ``_resolve_bmi(loinc_map=...)`` and ``_pick_from_loinc_map`` is
    only exercised via the orchestration test that stubs ``_resolve_bmi``
    itself.
    """
    height = SimpleNamespace(
        value="68",
        units="in",
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    weight = SimpleNamespace(
        value="160",  # lb
        units="lb",
        effective_datetime=dt.datetime(2026, 4, 10),
    )
    loinc_map = {
        chart_data.LOINC_BODY_HEIGHT: height,
        chart_data.LOINC_BODY_WEIGHT: weight,
    }
    # The batched-map path must NOT fall back to per-LOINC fetches when
    # the map already has what it needs.
    with patch.object(chart_data, "_latest_observation_by_loinc") as fallback_mock:
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            out = chart_data._resolve_bmi("p1", loinc_map=loinc_map)
    assert out is not None
    # 160 lb / (68 in)^2 ≈ 24.3 BMI
    assert 23.5 < out.value < 25.0
    assert out.clinical_date == "2026-04-10"  # latest of the two
    fallback_mock.assert_not_called()


def test_resolve_bmi_loinc_map_falls_back_to_direct_bmi_when_height_weight_absent() -> None:
    """When the batched map has no height/weight (e.g. patient had a
    standalone BMI observation only), the resolver must still fall
    back to the direct LOINC 39156-5 / ``body_mass_index`` paths."""
    direct_bmi = _stub_observation("29.4")
    loinc_map: dict = {chart_data.LOINC_BMI: direct_bmi}
    # No height or weight in the map, no name-based fallback either.
    with patch.object(chart_data, "_latest_observation_by_loinc") as fallback_mock:
        # Height + weight loinc-only fallbacks fire because the map lacks them,
        # then return None to keep falling through to direct-BMI which the
        # map has.
        fallback_mock.return_value = None
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            out = chart_data._resolve_bmi("p1", loinc_map=loinc_map)
    assert out is not None and out.value == 29.4


def test_resolve_egfr_returns_value() -> None:
    obs = _stub_observation("82")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = chart_data._resolve_egfr("p1")
    assert out is not None and out.value == 82.0


def test_resolve_egfr_none_when_missing() -> None:
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        assert chart_data._resolve_egfr("p1") is None


def test_resolve_egfr_none_when_value_unparsable() -> None:
    obs = _stub_observation("nope")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        assert chart_data._resolve_egfr("p1") is None


def test_resolve_bp_treatment_and_statin_delegate_to_hint_search() -> None:
    cv = ChartValue(value=1, clinical_date="2025-01-01")
    with patch.object(chart_data, "_resolve_active_medication_flag", return_value=cv):
        assert chart_data._resolve_bp_treatment("p1") is cv
        assert chart_data._resolve_statin("p1") is cv


# -- source-field provenance ------------------------------------------------


def test_resolve_sex_source_is_patient_record() -> None:
    male = SimpleNamespace(sex_at_birth="M")
    out = chart_data._resolve_sex(male)
    assert out is not None
    assert out.source == chart_data.SOURCE_PATIENT_RECORD
    assert out.clinical_date is None


def test_resolve_age_source_is_patient_record() -> None:
    patient = MagicMock()
    patient.birth_date = dt.date(1970, 1, 1)
    patient.age_at.return_value = 56.0
    out = chart_data._resolve_age(patient)
    assert out is not None
    assert out.source == chart_data.SOURCE_PATIENT_RECORD
    assert out.clinical_date is None


def test_resolve_diabetes_default_source_is_no_record() -> None:
    qs = MagicMock()
    qs.active.return_value.filter.return_value.prefetch_related.return_value.order_by.return_value = []
    with patch.object(chart_data.Condition, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = chart_data._resolve_diabetes("p1")
    assert out is not None
    assert out.source == chart_data.SOURCE_DEFAULT_NO_RECORD
    assert out.clinical_date is None


def test_resolve_diabetes_match_source_is_condition() -> None:
    coding = SimpleNamespace(code="E11.9")
    condition = SimpleNamespace(
        codings=SimpleNamespace(all=lambda: [coding]),
        onset_date=dt.date(2024, 7, 1),
    )
    qs = MagicMock()
    qs.active.return_value.filter.return_value.prefetch_related.return_value.order_by.return_value = [condition]
    with patch.object(chart_data.Condition, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = chart_data._resolve_diabetes("p1")
    assert out is not None
    assert out.source == chart_data.SOURCE_CONDITION
    assert out.clinical_date == "2024-07-01"


def test_resolve_active_medication_match_source_is_medication() -> None:
    statin = _stub_medication("Atorvastatin 20 MG Oral Tablet")
    qs = MagicMock()
    qs.active.return_value.prefetch_related.return_value = [statin]
    with patch.object(chart_data.Medication, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = chart_data._resolve_active_medication_flag("p1", ("statin",))
    assert out.source == chart_data.SOURCE_MEDICATION
    assert out.clinical_date is not None


def test_resolve_active_medication_default_source_is_no_record() -> None:
    qs = MagicMock()
    qs.active.return_value.prefetch_related.return_value = []
    with patch.object(chart_data.Medication, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = chart_data._resolve_active_medication_flag("p1", ("statin",))
    assert out.source == chart_data.SOURCE_DEFAULT_NO_RECORD
    assert out.clinical_date is None


def test_resolve_observation_value_keeps_default_observation_source() -> None:
    obs = _stub_observation("210")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = chart_data._resolve_total_cholesterol("p1")
    assert out is not None
    assert out.source == chart_data.SOURCE_OBSERVATION
    assert out.clinical_date == "2026-03-10"


# -- BMI unit-conversion edge cases ----------------------------------------


def test_weight_to_kg_supports_canvas_oz_default() -> None:
    # 2880 oz = 180 lb ≈ 81.65 kg
    out = chart_data._weight_to_kg(2880.0, "")
    assert out is not None
    assert abs(out - 81.65) < 0.05


def test_weight_to_kg_supports_lb_and_kg_units() -> None:
    out_lb = chart_data._weight_to_kg(180.0, "lb")
    out_kg = chart_data._weight_to_kg(82.0, "kg")
    assert out_lb is not None and abs(out_lb - 81.65) < 0.05
    assert out_kg == 82.0


def test_weight_to_kg_returns_none_for_unknown_units() -> None:
    assert chart_data._weight_to_kg(10.0, "stones") is None


def test_weight_to_kg_empty_units_picks_lb_for_typical_adult_lb_value() -> None:
    """180 with empty units (likely lb from FHIR/CCDA import) → ~81.6 kg.

    Regression guard: previously empty-units defaulted to oz, which made a
    150-lb patient look like a 4.25-kg infant and produced BMI ≈ 1.5.
    """
    out = chart_data._weight_to_kg(180.0, "")
    assert out is not None
    assert 80.0 < out < 85.0


def test_weight_to_kg_empty_units_picks_kg_for_low_value() -> None:
    """A value of 75 with empty units is most likely kilograms."""
    assert chart_data._weight_to_kg(75.0, "") == 75.0


def test_weight_to_kg_empty_units_at_150_treats_as_lb_not_kg() -> None:
    """Regression: a 150 lb adult (extremely common US weight) stored
    with empty units was previously misread as 150 kg, producing
    BMI ≈ 47 — a value the sanity guard [10..80] does NOT catch. After
    lowering the kg/lb threshold to 100, 150 is treated as lb."""
    out = chart_data._weight_to_kg(150.0, "")
    assert out is not None
    # 150 lb ≈ 68 kg
    assert 67.0 < out < 69.0


def test_weight_to_kg_empty_units_at_100_lb_threshold() -> None:
    """Boundary: at exactly 100, we treat as lb (US adult default)."""
    out = chart_data._weight_to_kg(100.0, "")
    assert out is not None
    # 100 lb ≈ 45.4 kg
    assert 45.0 < out < 46.0


def test_weight_to_kg_empty_units_at_99_kg_below_threshold() -> None:
    """Boundary: at 99, we treat as kg (catches European / kg-stored
    adults below the typical-lb range)."""
    assert chart_data._weight_to_kg(99.0, "") == 99.0


def test_weight_to_kg_empty_units_picks_oz_for_canvas_native_value() -> None:
    """Canvas Vitals command stores weight in oz; values ≥1000 with
    empty units fall into the oz path (typical adult oz ≈ 1500–9000)."""
    out = chart_data._weight_to_kg(2400.0, "")
    assert out is not None
    assert 65.0 < out < 70.0  # 2400 oz = 150 lb ≈ 68 kg


def test_weight_to_kg_empty_units_350_lb_obese_adult_treated_as_lb() -> None:
    """A 350 lb adult stored with empty units: must stay in the lb
    path, not flip to oz. Threshold for oz is 1000."""
    out = chart_data._weight_to_kg(350.0, "")
    assert out is not None
    # 350 lb ≈ 158.8 kg, NOT 350 oz ≈ 9.9 kg
    assert 155.0 < out < 162.0


def test_height_to_m_empty_units_picks_cm_for_large_value() -> None:
    """A height value of 178 with empty units is most likely cm."""
    out = chart_data._height_to_m(178.0, "")
    assert out is not None
    assert out == 1.78


def test_height_to_m_empty_units_picks_meters_for_small_value() -> None:
    """A height value below 3 with empty units is most likely meters."""
    assert chart_data._height_to_m(1.75, "") == 1.75


def test_resolve_bmi_handles_fhir_imported_lb_weight_without_units() -> None:
    """Regression test for the BMI = 1.5 bug at vicert-testing.

    FHIR-imported weight observations sometimes store the value in pounds
    with an empty ``units`` field. With the old code those got
    interpreted as ounces and produced an implausible BMI ≈ 1.5. The
    magnitude heuristic in ``_weight_to_kg`` now treats them as pounds.
    """
    height = SimpleNamespace(
        value="70",  # inches
        units="",
        effective_datetime=dt.datetime(2026, 5, 1),
    )
    weight = SimpleNamespace(
        value="180",  # lb (no units recorded)
        units="",
        effective_datetime=dt.datetime(2026, 5, 1),
    )
    with patch.object(chart_data, "_latest_observation_by_loinc") as loinc_mock:
        loinc_mock.side_effect = [height, weight]
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            out = chart_data._resolve_bmi("p1")
    assert out is not None
    # 180 lb / (70 in)² ≈ 25.8 BMI
    assert 24.0 < out.value < 27.0


def test_resolve_bmi_sanity_range_rejects_absurd_values() -> None:
    """If unit heuristics still misfire, a BMI outside [10, 80] falls
    back to the direct-BMI lookup rather than emitting garbage."""
    height = SimpleNamespace(
        value="1.78",  # would be interpreted as meters (heuristic)
        units="",
        effective_datetime=dt.datetime(2026, 5, 1),
    )
    weight = SimpleNamespace(
        value="1",  # 1 kg — absurdly low, computed BMI ≈ 0.32
        units="kg",
        effective_datetime=dt.datetime(2026, 5, 1),
    )
    fallback_bmi = _stub_observation("27.5")
    with patch.object(chart_data, "_latest_observation_by_loinc") as loinc_mock:
        # Height lookup, weight lookup, then direct-BMI lookup
        loinc_mock.side_effect = [height, weight, fallback_bmi]
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            out = chart_data._resolve_bmi("p1")
    assert out is not None
    assert out.value == 27.5  # direct-BMI fallback wins


def test_height_to_m_supports_canvas_inches_default() -> None:
    # 70 in ≈ 1.778 m
    out = chart_data._height_to_m(70.0, "")
    assert out is not None
    assert abs(out - 1.778) < 0.01


def test_height_to_m_supports_cm_and_m_units() -> None:
    assert chart_data._height_to_m(180.0, "cm") == 1.80
    assert chart_data._height_to_m(1.75, "m") == 1.75


def test_resolve_bmi_uses_height_weight_units() -> None:
    """Height in cm + weight in kg should produce metric BMI directly."""
    height = SimpleNamespace(
        value="180",
        units="cm",
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    weight = SimpleNamespace(
        value="82",
        units="kg",
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    with patch.object(chart_data, "_latest_observation_by_loinc") as loinc_mock:
        loinc_mock.side_effect = [height, weight]
        with patch.object(chart_data, "_latest_observation_by_name", return_value=None):
            out = chart_data._resolve_bmi("p1")
    # 82 / (1.8 * 1.8) = 25.31
    assert out is not None
    assert abs(out.value - 25.3) < 0.2


# -- Tobacco status (SNOMED-coded observation + interview fallback) --------


def test_resolve_smoking_accepts_loinc_39240_7() -> None:
    """Canvas Tobacco questionnaire codes observations as LOINC 39240-7,
    not 72166-2 — both should be honoured on read."""
    obs = SimpleNamespace(
        value_codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(code="449868002")]  # smokes daily
        ),
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = chart_data._resolve_smoking("p1")
    assert out is not None and out.value == 1


def test_resolve_smoking_falls_back_to_interview_response() -> None:
    """When the patient has no smoking Observation but the Tobacco
    questionnaire has been completed, read the latest response and look
    up the underlying Note for its clinical date."""
    response_option = SimpleNamespace(code="449868002")  # current daily smoker
    interview = SimpleNamespace(note_id=42)
    response = SimpleNamespace(
        response_option=response_option, interview=interview
    )
    note_obj = SimpleNamespace(datetime_of_service=dt.datetime(2026, 3, 15, 9, 0))
    note_qs = MagicMock()
    note_qs.only.return_value.first.return_value = note_obj

    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        with patch.object(
            chart_data,
            "_latest_tobacco_interview_response",
            return_value=response,
        ):
            with patch.object(chart_data.Note, "objects") as mocked_notes:
                mocked_notes.filter.return_value = note_qs
                out = chart_data._resolve_smoking("p1")
    assert out is not None
    assert out.value == 1
    assert out.clinical_date == "2026-03-15"


def test_resolve_smoking_picks_up_snomed_coded_observation() -> None:
    """Observation 101 at vicert-testing carries a SNOMED coding (no
    LOINC) and was previously missed. We now look it up via the SNOMED
    code system as a fallback after LOINC.
    """
    snomed_obs = SimpleNamespace(
        value_codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(code="449868002")]  # smokes daily
        ),
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    with patch.object(
        chart_data, "_latest_observation_by_loinc", return_value=None
    ), patch.object(
        chart_data, "_latest_observation_by_snomed", return_value=snomed_obs
    ), patch.object(
        chart_data, "_latest_smoking_observation_by_name", return_value=None
    ):
        out = chart_data._resolve_smoking("p1")
    assert out is not None and out.value == 1


def test_resolve_smoking_picks_up_name_based_observation() -> None:
    """Last-resort path: an observation with no LOINC/SNOMED coding but
    a tobacco-related ``name`` field still gets read."""
    name_obs = SimpleNamespace(
        value_codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(code="266919005")]  # never smoker
        ),
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    with patch.object(
        chart_data, "_latest_observation_by_loinc", return_value=None
    ), patch.object(
        chart_data, "_latest_observation_by_snomed", return_value=None
    ), patch.object(
        chart_data, "_latest_smoking_observation_by_name", return_value=name_obs
    ):
        out = chart_data._resolve_smoking("p1")
    assert out is not None and out.value == 0


def test_resolve_smoking_unrecognised_value_codes_falls_through_to_questionnaire() -> None:
    """If we find an observation but its value_codings aren't in either
    the current-smoker or non-current set, we should fall through to the
    Tobacco questionnaire path rather than guessing."""
    obs_with_unknown_value = SimpleNamespace(
        value_codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(code="999999999")]  # not in either set
        ),
        effective_datetime=dt.datetime(2026, 4, 1),
    )
    response_option = SimpleNamespace(code="449868002")
    response = SimpleNamespace(
        response_option=response_option,
        interview=SimpleNamespace(note_id=99),
    )
    note_obj = SimpleNamespace(datetime_of_service=dt.datetime(2026, 4, 5))
    note_qs = MagicMock()
    note_qs.only.return_value.first.return_value = note_obj
    with patch.object(
        chart_data, "_latest_observation_by_loinc", return_value=obs_with_unknown_value
    ), patch.object(
        chart_data, "_latest_tobacco_interview_response", return_value=response
    ), patch.object(chart_data.Note, "objects") as mocked_notes:
        mocked_notes.filter.return_value = note_qs
        out = chart_data._resolve_smoking("p1")
    assert out is not None
    assert out.value == 1
    assert out.clinical_date == "2026-04-05"  # questionnaire date, not obs date


def test_resolve_smoking_interview_with_former_user_is_zero() -> None:
    response_option = SimpleNamespace(code="8517006")  # former user
    response = SimpleNamespace(
        response_option=response_option, interview=SimpleNamespace(note_id=None)
    )
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        with patch.object(
            chart_data,
            "_latest_tobacco_interview_response",
            return_value=response,
        ):
            out = chart_data._resolve_smoking("p1")
    assert out is not None and out.value == 0


# -- HbA1c / UACR resolvers ------------------------------------------------


def test_resolve_hba1c_returns_value_when_present() -> None:
    obs = _stub_observation("7.2")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = chart_data._resolve_hba1c("p1")
    assert out is not None and out.value == 7.2


def test_resolve_hba1c_none_when_missing() -> None:
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        assert chart_data._resolve_hba1c("p1") is None


def test_resolve_uacr_returns_value_when_present() -> None:
    obs = _stub_observation("35.0")
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=obs):
        out = chart_data._resolve_uacr("p1")
    assert out is not None and out.value == 35.0


def test_resolve_uacr_none_when_missing() -> None:
    with patch.object(chart_data, "_latest_observation_by_loinc", return_value=None):
        assert chart_data._resolve_uacr("p1") is None


# -- Batched-fetch helpers (database-performance review) --------------------


def test_pick_from_loinc_map_returns_newest_among_candidates() -> None:
    """When a resolver accepts multiple equivalent LOINC codes (eGFR
    2021 and 2009), the batched picker must return whichever is newest."""
    new = SimpleNamespace(effective_datetime=dt.datetime(2026, 5, 1))
    old = SimpleNamespace(effective_datetime=dt.datetime(2025, 1, 1))
    loinc_map = {"98979-8": new, "48642-3": old}
    out = chart_data._pick_from_loinc_map(loinc_map, ("98979-8", "48642-3"))
    assert out is new


def test_pick_from_loinc_map_none_when_no_matching_code() -> None:
    loinc_map = {"2093-3": SimpleNamespace(effective_datetime=dt.datetime.now())}
    assert chart_data._pick_from_loinc_map(loinc_map, ("9999-9",)) is None
    assert chart_data._pick_from_loinc_map(None, ("2093-3",)) is None
    assert chart_data._pick_from_loinc_map({}, ("2093-3",)) is None


def test_resolve_total_cholesterol_uses_loinc_map_when_provided() -> None:
    """When ``loinc_map`` is passed, the resolver MUST NOT fire its own
    per-LOINC fetch — that's the whole point of the batched path."""
    cached_obs = _stub_observation("210")
    loinc_map = {chart_data.LOINC_TOTAL_CHOLESTEROL: cached_obs}
    with patch.object(
        chart_data, "_latest_observation_by_loinc"
    ) as fetch_mock:
        out = chart_data._resolve_total_cholesterol("p1", loinc_map=loinc_map)
    assert out is not None and out.value == 210.0
    fetch_mock.assert_not_called()


def test_fetch_active_medications_returns_list() -> None:
    """Verify the deduped active-medications fetch materialises the
    queryset (so the two downstream matchers don't re-execute it)."""
    med_a = _stub_medication("Atorvastatin 20 MG Oral Tablet")
    qs = MagicMock()
    qs.active.return_value.prefetch_related.return_value = [med_a]
    with patch.object(chart_data.Medication, "objects") as mocked:
        mocked.for_patient.return_value = qs
        out = chart_data._fetch_active_medications("p1")
    assert out == [med_a]
    mocked.for_patient.assert_called_once_with("p1")


def test_match_medication_by_hints_matches_or_defaults() -> None:
    statin = _stub_medication("Atorvastatin 20 MG Oral Tablet")
    aspirin = _stub_medication("Aspirin 81 MG Oral Tablet")
    hit = chart_data._match_medication_by_hints([aspirin, statin], ("atorvastatin",))
    miss = chart_data._match_medication_by_hints([aspirin], ("statin",))
    assert hit.value == 1
    assert hit.source == chart_data.SOURCE_MEDICATION
    assert miss.value == 0
    assert miss.source == chart_data.SOURCE_DEFAULT_NO_RECORD
