"""Tests for CKM/eCKM measure gathering: unit normalization, BMI derivation,
waist source-code aliasing, and skip-blank latest-value selection."""
from types import SimpleNamespace
from unittest.mock import patch

from cms_access_fhir_client.api.operations_api import (
    _compute_bmi,
    _gather_measures,
    _to_kg,
    _to_meters,
)


def _obs(value, units):
    return SimpleNamespace(value=value, units=units)


class TestUnitConversions:
    def test_to_kg(self):
        assert _to_kg(70, "kg") == 70
        assert _to_kg(1000, "g") == 1.0
        assert round(_to_kg(2400, "oz"), 1) == 68.0
        assert round(_to_kg(150, "lb"), 1) == 68.0
        assert _to_kg(150, "[lb_av]") == 150 * 0.45359237
        assert _to_kg(10, "stone") is None  # unknown unit

    def test_to_meters(self):
        assert _to_meters(2, "m") == 2
        assert _to_meters(165, "cm") == 1.65
        assert round(_to_meters(65, "in"), 3) == 1.651
        assert _to_meters(5, "furlong") is None


class TestComputeBmi:
    def test_from_height_and_weight(self):
        def fake(_pid, codes):
            codes = set(codes)
            if "8302-2" in codes:
                return _obs("65", "in")
            if "29463-7" in codes:
                return _obs("2400", "oz")  # 150 lb
            return None

        with patch("cms_access_fhir_client.api.operations_api._latest_valued_observation", side_effect=fake):
            bmi = _compute_bmi("p-1")
        assert bmi == {"value": 25.0, "unit": "kg/m2"}

    def test_none_when_height_missing(self):
        def fake(_pid, codes):
            return _obs("2400", "oz") if "29463-7" in set(codes) else None

        with patch("cms_access_fhir_client.api.operations_api._latest_valued_observation", side_effect=fake):
            assert _compute_bmi("p-1") is None


class TestGatherMeasures:
    def _fake_latest(self, _pid, codes):
        codes = set(codes)
        if "29463-7" in codes:
            return _obs("2400", "oz")
        if "8302-2" in codes:
            return _obs("65", "in")
        if "8280-0" in codes or "56086-2" in codes:  # waist via Canvas alias
            return _obs("94", "cm")
        if "4548-4" in codes:
            return _obs("9", "%")
        if "18262-6" in codes:
            return _obs("33", "mg/dL")
        return None  # BMI (39156-5) not stored → forces derivation

    def test_eckm_normalizes_weight_derives_bmi_and_maps_waist(self):
        with (
            patch("cms_access_fhir_client.api.operations_api._latest_valued_observation", side_effect=self._fake_latest),
            patch("cms_access_fhir_client.api.operations_api._latest_bp_components",
                  return_value={"8480-6": 180.0, "8462-4": 90.0}),
        ):
            measures = _gather_measures("p-1", "eCKM")

        assert measures["85354-9"] == {"components": {"8480-6": 180.0, "8462-4": 90.0}}
        assert measures["29463-7"] == {"value": 68.0, "unit": "kg"}   # 2400 oz → kg
        assert measures["39156-5"] == {"value": 25.0, "unit": "kg/m2"}  # derived
        assert measures["8280-0"] == {"value": 94.0, "unit": "cm"}    # via 56086-2 alias
        assert measures["4548-4"] == {"value": 9.0, "unit": "%"}
        assert measures["18262-6"] == {"value": 33.0, "unit": "mg/dL"}
        # eCKM excludes eGFR/uACR
        assert "98979-8" not in measures
        assert "14959-1" not in measures

    def test_unknown_weight_unit_is_skipped(self):
        def fake(_pid, codes):
            return _obs("10", "stone") if "29463-7" in set(codes) else None

        with (
            patch("cms_access_fhir_client.api.operations_api._latest_valued_observation", side_effect=fake),
            patch("cms_access_fhir_client.api.operations_api._latest_bp_components", return_value=None),
        ):
            measures = _gather_measures("p-1", "eCKM")
        assert "29463-7" not in measures

    def test_missing_measures_omitted(self):
        with (
            patch("cms_access_fhir_client.api.operations_api._latest_valued_observation", return_value=None),
            patch("cms_access_fhir_client.api.operations_api._latest_bp_components", return_value=None),
        ):
            measures = _gather_measures("p-1", "eCKM")
        assert measures == {}
