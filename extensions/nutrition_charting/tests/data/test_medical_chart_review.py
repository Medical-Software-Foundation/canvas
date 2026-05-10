"""Phase B tests for the chart-extraction module.

The functions hit Django ORM models, so each test patches the relevant model
class at the import site in `medical_chart_review` and feeds in MagicMock
querysets shaped to match what the real ORM would return.
"""

from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from nutrition_charting.data import medical_chart_review as mcr


def _coding(code: str = "", system: str = "", display: str = "") -> MagicMock:
    c = MagicMock()
    c.code = code
    c.system = system
    c.display = display
    return c


def _condition(display: str, code: str = "I10", system: str = "ICD-10") -> MagicMock:
    cond = MagicMock()
    # _first_coding now reads from the prefetched cache via codings.all()
    # — test mocks shape it as a list rather than calling .first().
    cond.codings.all.return_value = [_coding(code=code, system=system, display=display)]
    return cond


def _allergy(display: str, severity: str = "", narrative: str = "") -> MagicMock:
    a = MagicMock()
    a.codings.all.return_value = [_coding(display=display)] if display else []
    a.severity = severity
    a.narrative = narrative
    return a


def _med(display: str) -> MagicMock:
    m = MagicMock()
    m.codings.all.return_value = [_coding(display=display)]
    return m


# ---- get_age ----

def test_age_birthday_already_passed_this_year() -> None:
    assert mcr.get_age(date(1990, 1, 15), today=date(2026, 5, 4)) == 36


def test_age_birthday_not_yet_this_year() -> None:
    assert mcr.get_age(date(1990, 12, 15), today=date(2026, 5, 4)) == 35


def test_age_none_birth_date_returns_none() -> None:
    assert mcr.get_age(None, today=date(2026, 5, 4)) is None


def test_age_future_birth_date_clamped_to_zero() -> None:
    assert mcr.get_age(date(2030, 1, 1), today=date(2026, 5, 4)) == 0


# ---- _matches_nutrition_drug_class ----

def test_drug_class_matches_glp1() -> None:
    assert mcr._matches_nutrition_drug_class("Semaglutide 0.5mg/ML INJ")


def test_drug_class_matches_case_insensitive() -> None:
    assert mcr._matches_nutrition_drug_class("METFORMIN HCL 500mg")


def test_drug_class_skips_unrelated_drug() -> None:
    assert not mcr._matches_nutrition_drug_class("Lisinopril 10mg")


def test_drug_class_handles_blank() -> None:
    assert not mcr._matches_nutrition_drug_class("")


# ---- get_anthropometrics ----

@patch("nutrition_charting.data.medical_chart_review.Observation")
def test_anthropometrics_returns_latest_height_and_weight(mock_obs: MagicMock) -> None:
    mock_obs.objects.filter.return_value.order_by.return_value.values.return_value = [
        {"codings__code": "8302-2", "value": "67", "units": "in",
         "effective_datetime": datetime(2026, 4, 1)},
        {"codings__code": "29463-7", "value": "165", "units": "lbs",
         "effective_datetime": datetime(2026, 4, 1)},
        # Older row should be ignored
        {"codings__code": "8302-2", "value": "65", "units": "in",
         "effective_datetime": datetime(2025, 1, 1)},
    ]

    out = mcr.get_anthropometrics("pat-1")

    # Locks in the `entered_in_error__isnull=True` filter on Observation —
    # without it, a retracted height/weight could pre-fill the form and be
    # re-emitted as a VitalsCommand on save.
    mock_obs.objects.filter.assert_called_once_with(
        patient__id="pat-1",
        codings__code__in=["8302-2", "29463-7"],
        codings__system="http://loinc.org",
        deleted=False,
        entered_in_error__isnull=True,
    )
    assert out["height"] == "67"
    assert out["weight"] == "165"
    assert out["height_units"] == "in"
    assert out["weight_units"] == "lbs"
    assert out["height_date"] == "2026-04-01"


@patch("nutrition_charting.data.medical_chart_review.Observation")
def test_anthropometrics_empty_when_no_observations(mock_obs: MagicMock) -> None:
    mock_obs.objects.filter.return_value.order_by.return_value.values.return_value = []

    out = mcr.get_anthropometrics("pat-1")

    assert out == {
        "height": None, "height_units": "", "height_date": "",
        "weight": None, "weight_units": "", "weight_date": "",
    }


# ---- get_pmh ----

@patch("nutrition_charting.data.medical_chart_review.Condition")
def test_pmh_returns_active_conditions_with_codings(mock_cond: MagicMock) -> None:
    qs = mock_cond.objects.for_patient.return_value.filter.return_value.order_by.return_value
    qs.prefetch_related.return_value = [
        _condition("Type 2 diabetes mellitus", code="E11.9"),
        _condition("Essential hypertension", code="I10"),
    ]

    out = mcr.get_pmh("pat-1")

    mock_cond.objects.for_patient.assert_called_once_with("pat-1")
    # Locks in the `entered_in_error__isnull=True` filter — without it,
    # retracted conditions surface in the chart review and become
    # selectable indications on emitted Refer commands.
    mock_cond.objects.for_patient.return_value.filter.assert_called_once_with(
        clinical_status="active",
        deleted=False,
        entered_in_error__isnull=True,
    )
    qs.prefetch_related.assert_called_once_with("codings")
    assert [c["display"] for c in out] == [
        "Type 2 diabetes mellitus", "Essential hypertension",
    ]
    assert [c["code"] for c in out] == ["E11.9", "I10"]


@patch("nutrition_charting.data.medical_chart_review.Condition")
def test_pmh_skips_conditions_without_codings(mock_cond: MagicMock) -> None:
    bare = MagicMock()
    bare.codings.all.return_value = []
    qs = mock_cond.objects.for_patient.return_value.filter.return_value.order_by.return_value
    qs.prefetch_related.return_value = [bare]

    assert mcr.get_pmh("pat-1") == []


# ---- get_allergies ----

@patch("nutrition_charting.data.medical_chart_review.AllergyIntolerance")
def test_allergies_uses_display_or_falls_back_to_narrative(mock_a: MagicMock) -> None:
    qs = mock_a.objects.for_patient.return_value.filter.return_value
    qs.prefetch_related.return_value = [
        _allergy("Peanut", severity="severe"),
        _allergy("", narrative="Shellfish (anaphylaxis)"),
        _allergy("", narrative=""),  # skipped
    ]

    out = mcr.get_allergies("pat-1")

    # Locks in the `entered_in_error__isnull=True` filter on AllergyIntolerance.
    mock_a.objects.for_patient.return_value.filter.assert_called_once_with(
        status="active",
        deleted=False,
        entered_in_error__isnull=True,
    )
    qs.prefetch_related.assert_called_once_with("codings")
    assert [a["display"] for a in out] == ["Peanut", "Shellfish (anaphylaxis)"]
    assert out[0]["severity"] == "severe"


# ---- get_nutrition_medications ----

@patch("nutrition_charting.data.medical_chart_review.Medication")
def test_meds_filtered_to_nutrition_drug_classes(mock_med: MagicMock) -> None:
    # Chain reflects `.for_patient(...).active().filter(...).prefetch_related(...)`.
    # `.active()` is the canonical "currently taking" filter — using
    # `.filter(status="active")` instead would surface expired Rx + supplies.
    qs = mock_med.objects.for_patient.return_value.active.return_value.filter.return_value
    qs.prefetch_related.return_value = [
        _med("Semaglutide 1mg/dose"),
        _med("Lisinopril 10mg"),  # not nutrition-relevant — filtered out
        _med("Atorvastatin 20mg"),
    ]

    out = mcr.get_nutrition_medications("pat-1")

    qs.prefetch_related.assert_called_once_with("codings")
    mock_med.objects.for_patient.return_value.active.assert_called_once_with()
    assert [m["display"] for m in out] == [
        "Semaglutide 1mg/dose", "Atorvastatin 20mg",
    ]


# ---- get_recent_nutrition_labs ----

@patch("nutrition_charting.data.medical_chart_review.Observation")
def test_recent_labs_returns_latest_per_loinc_within_window(mock_obs: MagicMock) -> None:
    mock_obs.objects.filter.return_value.order_by.return_value.values.return_value = [
        {"codings__code": "4548-4", "value": "6.8", "units": "%",
         "effective_datetime": datetime(2026, 4, 10)},
        {"codings__code": "2093-3", "value": "210", "units": "mg/dL",
         "effective_datetime": datetime(2026, 3, 1)},
        # Older A1c — skipped
        {"codings__code": "4548-4", "value": "7.5", "units": "%",
         "effective_datetime": datetime(2026, 1, 1)},
    ]

    out = mcr.get_recent_nutrition_labs("pat-1", today=date(2026, 5, 4))

    # Locks in the `entered_in_error__isnull=True` filter on Observation —
    # without it, retracted lab values could anchor a nutrition plan.
    filter_kwargs = mock_obs.objects.filter.call_args.kwargs
    assert filter_kwargs["deleted"] is False
    assert filter_kwargs["entered_in_error__isnull"] is True

    assert [lab["code"] for lab in out] == ["4548-4", "2093-3"]
    assert out[0]["label"] == "Hemoglobin A1c"
    assert out[0]["value"] == "6.8"
    assert out[0]["effective_date"] == "2026-04-10"


# ---- build_chart_review (integration through the helpers) ----

@patch("nutrition_charting.data.medical_chart_review.get_nutrition_medications", return_value=[])
@patch("nutrition_charting.data.medical_chart_review.get_recent_nutrition_labs", return_value=[])
@patch("nutrition_charting.data.medical_chart_review.get_allergies", return_value=[])
@patch("nutrition_charting.data.medical_chart_review.get_pmh", return_value=[])
@patch("nutrition_charting.data.medical_chart_review.get_anthropometrics",
       return_value={"height": "67", "weight": "165",
                     "height_units": "in", "weight_units": "lbs",
                     "height_date": "", "weight_date": ""})
@patch("nutrition_charting.data.medical_chart_review.Patient")
def test_build_chart_review_assembles_full_payload(
    mock_patient: MagicMock,
    *_: MagicMock,
) -> None:
    patient = MagicMock()
    patient.birth_date = date(1990, 5, 4)
    patient.sex_at_birth = "F"
    mock_patient.objects.get.return_value = patient

    out = mcr.build_chart_review("pat-1", today=date(2026, 5, 4))

    assert out["missing"] is False
    assert out["age"] == 36
    assert out["sex"] == "F"
    assert out["anthropometrics"]["height"] == "67"


def test_build_chart_review_handles_blank_patient_id() -> None:
    assert mcr.build_chart_review("") == {"missing": True, "patient_id": ""}


@patch("nutrition_charting.data.medical_chart_review.Patient")
def test_build_chart_review_returns_missing_when_patient_not_found(mock_patient: MagicMock) -> None:
    class DoesNotExist(Exception):
        pass

    mock_patient.DoesNotExist = DoesNotExist
    mock_patient.objects.get.side_effect = DoesNotExist()

    assert mcr.build_chart_review("pat-1") == {"missing": True, "patient_id": "pat-1"}


# ---- per-request cache (Risk #2) ----

@patch("nutrition_charting.data.medical_chart_review._build_chart_review_uncached")
def test_build_chart_review_returns_cache_hit_without_recomputing(
    mock_build: MagicMock,
) -> None:
    """Same patient_id within one request returns the cached payload and
    skips the full chart-extraction path entirely."""
    cache: dict[str, Any] = {"pat-1": {"missing": False, "cached": True}}

    out = mcr.build_chart_review("pat-1", cache=cache)

    assert out == {"missing": False, "cached": True}
    mock_build.assert_not_called()


@patch("nutrition_charting.data.medical_chart_review._build_chart_review_uncached")
def test_build_chart_review_populates_cache_on_miss(mock_build: MagicMock) -> None:
    """First call for a patient_id computes + stashes; subsequent calls in
    the same request reuse the stashed payload."""
    mock_build.return_value = {"missing": False, "patient_id": "pat-1"}
    cache: dict[str, Any] = {}

    out1 = mcr.build_chart_review("pat-1", cache=cache)
    out2 = mcr.build_chart_review("pat-1", cache=cache)

    assert out1 == out2 == {"missing": False, "patient_id": "pat-1"}
    assert cache == {"pat-1": {"missing": False, "patient_id": "pat-1"}}
    mock_build.assert_called_once_with("pat-1", today=None)


@patch("nutrition_charting.data.medical_chart_review._build_chart_review_uncached")
def test_build_chart_review_runs_each_call_when_cache_is_none(
    mock_build: MagicMock,
) -> None:
    """Default behavior (no cache passed) is identical to pre-Phase-1B —
    every call hits the chart-extraction path."""
    mock_build.return_value = {"missing": False, "patient_id": "pat-1"}

    mcr.build_chart_review("pat-1")
    mcr.build_chart_review("pat-1")

    assert mock_build.call_count == 2
