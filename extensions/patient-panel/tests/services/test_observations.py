"""Tests for patient_panel.services.observations.

Unit conversion is pure; batch loaders use real Observation / ObservationCoding
records via the Django ORM (no mocking of canvas_sdk).
"""

__is_plugin__ = True

import math

import arrow
import pytest

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.observation import (
    Observation,
    ObservationCoding,
    ObservationComponent,
)
from canvas_sdk.v1.data.patient import Patient

from patient_panel.services.observations import (
    format_weight_lb_oz,
    load_observations_batch,
    load_vitals_batch,
    to_kilograms,
    to_meters,
)


# ── Unit conversion (pure) ────────────────────────────────────────────────

class TestWeightConversion:
    def test_kg_passthrough(self) -> None:
        assert to_kilograms(70.0, "kg") == 70.0

    def test_kg_uppercase(self) -> None:
        assert to_kilograms(70.0, "KG") == 70.0

    def test_pounds(self) -> None:
        result = to_kilograms(150.0, "lbs")
        assert result is not None
        assert math.isclose(result, 68.0388555)

    def test_pound_synonyms(self) -> None:
        for u in ("lb", "lbs", "pound", "pounds"):
            result = to_kilograms(1.0, u)
            assert result is not None
            assert math.isclose(result, 0.45359237)

    def test_grams(self) -> None:
        result = to_kilograms(500.0, "g")
        assert result is not None
        assert math.isclose(result, 0.5)

    def test_empty_units_defaults_to_kg(self) -> None:
        assert to_kilograms(70.0, "") == 70.0

    def test_unknown_units_returns_none(self) -> None:
        assert to_kilograms(70.0, "stone") is None


class TestFormatWeightLbOz:
    def test_oz_source_splits_lb_and_oz(self) -> None:
        # 200 oz = 12 lb 8 oz
        assert format_weight_lb_oz("200", "oz") == "12 lb 8 oz"

    def test_exact_pound_boundary(self) -> None:
        # 32 oz = 2 lb 0 oz
        assert format_weight_lb_oz("32", "oz") == "2 lb 0 oz"

    def test_lb_source(self) -> None:
        assert format_weight_lb_oz("10", "lb") == "10 lb 0 oz"

    def test_kg_source_rounds_to_whole_oz(self) -> None:
        # 1 kg ≈ 35.27 oz → 35 oz = 2 lb 3 oz
        assert format_weight_lb_oz("1", "kg") == "2 lb 3 oz"

    def test_sub_pound_value(self) -> None:
        assert format_weight_lb_oz("5", "oz") == "0 lb 5 oz"

    def test_non_numeric_returns_empty(self) -> None:
        assert format_weight_lb_oz("abc", "oz") == ""

    def test_unknown_units_returns_empty(self) -> None:
        assert format_weight_lb_oz("100", "stone") == ""


class TestHeightConversion:
    def test_meters_passthrough(self) -> None:
        assert to_meters(1.7, "m") == 1.7

    def test_centimeters(self) -> None:
        result = to_meters(170.0, "cm")
        assert result is not None
        assert math.isclose(result, 1.70)

    def test_millimeters(self) -> None:
        result = to_meters(1700.0, "mm")
        assert result is not None
        assert math.isclose(result, 1.70)

    def test_inches(self) -> None:
        result = to_meters(70.0, "in")
        assert result is not None
        assert math.isclose(result, 1.778)

    def test_feet(self) -> None:
        result = to_meters(6.0, "ft")
        assert result is not None
        assert math.isclose(result, 1.8288)

    def test_empty_units_defaults_to_cm(self) -> None:
        result = to_meters(170.0, "")
        assert result is not None
        assert math.isclose(result, 1.70)

    def test_unknown_units_returns_none(self) -> None:
        assert to_meters(170.0, "yards") is None


class TestBMIRealistic:
    def test_metric_inputs_yield_realistic_bmi(self) -> None:
        kg = to_kilograms(70.0, "kg")
        m = to_meters(170.0, "cm")
        assert kg is not None and m is not None
        bmi = kg / (m * m)
        assert 23.0 < bmi < 25.0

    def test_imperial_inputs_yield_realistic_bmi(self) -> None:
        kg = to_kilograms(154.0, "lbs")
        m = to_meters(67.0, "in")
        assert kg is not None and m is not None
        bmi = kg / (m * m)
        assert 23.0 < bmi < 25.0

    def test_mixed_units_kg_and_in(self) -> None:
        kg = to_kilograms(70.0, "kg")
        m = to_meters(67.0, "in")
        assert kg is not None and m is not None
        bmi = kg / (m * m)
        assert 23.0 < bmi < 25.0


# ── Batch loading (ORM) ───────────────────────────────────────────────────

pytestmark = pytest.mark.django_db


def _create_observation(
    patient: Patient,
    *,
    code: str,
    value: str = "",
    units: str = "",
    effective_datetime: object = None,
    name: str = "",
    category: str = "laboratory",
) -> Observation:
    obs = Observation.objects.create(
        patient=patient,
        category=category,
        value=value,
        units=units,
        name=name,
        effective_datetime=effective_datetime or arrow.utcnow().datetime,
        note_id=0,
        deleted=False,
    )
    ObservationCoding.objects.create(observation=obs, code=code, display="", system="")
    return obs


class TestLoadObservations:
    def test_returns_dict_keyed_by_loinc(self) -> None:
        result = load_observations_batch(
            patient_ids=["00000000-0000-0000-0000-000000000000"],
            loinc_codes=["4548-4", "39156-5"],
        )
        assert "4548-4" in result
        assert "39156-5" in result

    def test_deduplicates_to_most_recent(self) -> None:
        patient = PatientFactory.create()
        _create_observation(
            patient, code="4548-4", value="6.8", units="%",
            effective_datetime=arrow.get("2026-01-01T00:00:00+00:00").datetime,
        )
        _create_observation(
            patient, code="4548-4", value="7.2", units="%",
            effective_datetime=arrow.get("2026-04-01T00:00:00+00:00").datetime,
        )
        result = load_observations_batch(
            patient_ids=[str(patient.id)], loinc_codes=["4548-4"],
        )
        assert result["4548-4"][str(patient.id)]["value"] == "7.2"

    def test_empty_when_no_observations(self) -> None:
        result = load_observations_batch(
            patient_ids=["00000000-0000-0000-0000-000000000000"],
            loinc_codes=["4548-4"],
        )
        assert result["4548-4"] == {}

    def test_empty_loinc_codes_returns_empty(self) -> None:
        assert load_observations_batch(patient_ids=["any"], loinc_codes=[]) == {}

    def test_multiple_patients_multiple_loincs(self) -> None:
        p1 = PatientFactory.create()
        p2 = PatientFactory.create()
        _create_observation(p1, code="4548-4", value="7.2", units="%")
        _create_observation(p2, code="4548-4", value="5.9", units="%")
        _create_observation(p1, code="39156-5", value="24.5", units="kg/m2")

        result = load_observations_batch(
            patient_ids=[str(p1.id), str(p2.id)],
            loinc_codes=["4548-4", "39156-5"],
        )
        assert result["4548-4"][str(p1.id)]["value"] == "7.2"
        assert result["4548-4"][str(p2.id)]["value"] == "5.9"
        assert result["39156-5"][str(p1.id)]["value"] == "24.5"

    def test_deep_history_uses_single_streamed_query(self) -> None:
        """Perf guard (same failure class as the notes bug): loading
        observations for patients with deep history must NOT materialise the
        full history. It uses one streamed query over the coding table (no
        codings prefetch, no model hydration), so the query count stays at 1
        regardless of how many historical observations each patient has, and
        still returns the most recent value per code.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        p1 = PatientFactory.create()
        p2 = PatientFactory.create()
        for i in range(30):
            _create_observation(
                p1, code="4548-4", value=str(i), units="%",
                effective_datetime=arrow.utcnow().shift(days=-i).datetime,
            )
        _create_observation(p2, code="4548-4", value="5.0", units="%")

        with CaptureQueriesContext(connection) as ctx:
            result = load_observations_batch(
                patient_ids=[str(p1.id), str(p2.id)], loinc_codes=["4548-4"],
            )

        assert result["4548-4"][str(p1.id)]["value"] == "0"  # day -0 = newest
        assert result["4548-4"][str(p2.id)]["value"] == "5.0"
        assert len(ctx.captured_queries) == 1, [
            q["sql"] for q in ctx.captured_queries
        ]


def _create_vital(
    patient: Patient,
    *,
    name: str,
    value: str = "",
    units: str = "",
    category: str = "vital-signs",
) -> Observation:
    return Observation.objects.create(
        patient=patient,
        category=category,
        name=name,
        value=value,
        units=units,
        effective_datetime=arrow.utcnow().datetime,
        note_id=0,
        deleted=False,
    )


class TestLoadVitals:
    def test_empty_vital_names_returns_empty(self) -> None:
        assert load_vitals_batch(["any"], []) == {}

    def test_plain_vital_value_and_units(self) -> None:
        patient = PatientFactory.create()
        _create_vital(patient, name="weight", value="70", units="kg")
        result = load_vitals_batch([str(patient.id)], ["weight"])
        assert result["weight"][str(patient.id)] == {"value": "70", "units": "kg"}

    def test_bmi_calculated_from_weight_and_height(self) -> None:
        patient = PatientFactory.create()
        _create_vital(patient, name="weight", value="70", units="kg")
        _create_vital(patient, name="height", value="170", units="cm")
        result = load_vitals_batch([str(patient.id)], ["bmi"])
        bmi = float(result["bmi"][str(patient.id)]["value"])
        assert 23.0 < bmi < 25.0  # 70 / 1.7^2 ≈ 24.2
        # weight/height were only pulled in to compute bmi → not in result
        assert "weight" not in result
        assert "height" not in result

    def test_bmi_skipped_when_missing_height(self) -> None:
        patient = PatientFactory.create()
        _create_vital(patient, name="weight", value="70", units="kg")
        result = load_vitals_batch([str(patient.id)], ["bmi"])
        assert result["bmi"] == {}

    def test_blood_pressure_combined_from_components(self) -> None:
        patient = PatientFactory.create()
        # Top-level value empty → combine from components.
        bp = _create_vital(patient, name="blood_pressure", value="")
        ObservationComponent.objects.create(observation=bp, name="systolic", value_quantity="120")
        ObservationComponent.objects.create(observation=bp, name="diastolic", value_quantity="80")
        result = load_vitals_batch([str(patient.id)], ["blood_pressure"])
        entry = result["blood_pressure"][str(patient.id)]
        # NOTE: components are joined in order_by("name") order, so "diastolic"
        # (80) precedes "systolic" (120) → "80/120". This documents existing
        # behavior (pre-existing quirk, carried over verbatim in the refactor).
        assert entry["value"] == "80/120"
        assert entry["units"] == "mmHg"

    def test_deep_history_uses_single_streamed_query(self) -> None:
        """Perf guard (same failure class as the notes bug): vitals are streamed
        via .values().iterator(); query count stays at 1 regardless of how many
        historical vital rows a patient has, and the most recent value wins.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        patient = PatientFactory.create()
        for i in range(30):
            Observation.objects.create(
                patient=patient, category="vital-signs", name="weight",
                value=str(60 + i), units="kg",
                effective_datetime=arrow.utcnow().shift(days=-i).datetime,
                note_id=0, deleted=False,
            )
        with CaptureQueriesContext(connection) as ctx:
            result = load_vitals_batch([str(patient.id)], ["weight"])
        assert result["weight"][str(patient.id)]["value"] == "60"  # day -0 = newest
        assert len(ctx.captured_queries) == 1, [q["sql"] for q in ctx.captured_queries]

    def test_blood_pressure_backfill_multi_patient_single_query(self) -> None:
        """Two patients' BP must map to their own components (no cross-contam),
        and the component backfill is ONE query for all BP observations."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        p1 = PatientFactory.create()
        p2 = PatientFactory.create()
        bp1 = _create_vital(p1, name="blood_pressure", value="")
        ObservationComponent.objects.create(observation=bp1, name="systolic", value_quantity="120")
        ObservationComponent.objects.create(observation=bp1, name="diastolic", value_quantity="80")
        bp2 = _create_vital(p2, name="blood_pressure", value="")
        ObservationComponent.objects.create(observation=bp2, name="systolic", value_quantity="130")
        ObservationComponent.objects.create(observation=bp2, name="diastolic", value_quantity="85")

        with CaptureQueriesContext(connection) as ctx:
            result = load_vitals_batch([str(p1.id), str(p2.id)], ["blood_pressure"])

        assert result["blood_pressure"][str(p1.id)]["value"] == "80/120"
        assert result["blood_pressure"][str(p2.id)]["value"] == "85/130"
        # 1 query to stream the BP rows + 1 to backfill all components.
        assert len(ctx.captured_queries) == 2, [q["sql"] for q in ctx.captured_queries]
