"""Tests for the PREVENT calculator SimpleAPI route."""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.effects.simple_api import JSONResponse

from prevent_calculator.services.chart_data import ChartPrefill, ChartValue
from prevent_calculator.protocols.calculator_api import (
    PreventCalculatorAPI,
    _build_input_observation_effects,
    _build_observation_effects,
    _extract_diastolic_from_bp_value,
    _input_save_label,
    _parse_inputs,
    _safe_json_for_script,
    _save_systolic_bp_as_panel,
)
from prevent_calculator.services.equations import (
    PreventInput,
    PreventResult,
    SEX_FEMALE,
    SEX_MALE,
    compute_prevent_base,
)


class DummyRequest:
    """Stub for SimpleAPI Request — exposes only what the handlers consume."""

    def __init__(
        self,
        query_params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.query_params = query_params or {}
        self._body = body

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no body")
        return self._body


class DummyEvent:
    def __init__(self, context: dict[str, Any] | None = None) -> None:
        self.context = context or {}


def _make_api(
    method: str,
    path: str,
    query_params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> PreventCalculatorAPI:
    api = PreventCalculatorAPI(
        event=DummyEvent(context={"method": method, "path": path})
    )
    api.request = DummyRequest(query_params=query_params, body=body)
    return api


def _extract_response_json(effects: list[Any]) -> dict[str, Any]:
    """Pull the parsed body of a JSONResponse from the route's return list."""
    for effect in effects:
        if isinstance(effect, JSONResponse):
            content = effect.content
            if isinstance(content, bytes):
                return dict(json.loads(content.decode("utf-8")))
            if isinstance(content, str):
                return dict(json.loads(content))
            if isinstance(content, dict):
                return dict(content)
    raise AssertionError("no JSONResponse in effects")


def _count_observation_effects(effects: list[Any]) -> int:
    """Count CREATE_OBSERVATION effects in the route's return list."""
    return sum(
        1
        for e in effects
        if getattr(e, "type", None) == EffectType.CREATE_OBSERVATION
    )


# -- _parse_inputs -----------------------------------------------------------


def test_parse_inputs_minimal_required_fields() -> None:
    parsed = _parse_inputs(
        {
            "sex": "1",
            "age": "55",
            "systolic_bp": "130",
            "egfr": "85",
        }
    )
    assert isinstance(parsed, PreventInput)
    assert parsed.sex == 1
    assert parsed.age == 55
    assert parsed.sbp == 130
    assert parsed.egfr == 85
    assert parsed.dm == 0
    assert parsed.smoking == 0
    assert parsed.bptreat == 0
    assert parsed.statin is None
    assert parsed.tc is None


def test_to_int_flag_handles_bool_and_non_string_default() -> None:
    from prevent_calculator.protocols.calculator_api import _to_int_flag

    assert _to_int_flag(True) == 1
    assert _to_int_flag(False) == 0
    assert _to_int_flag([1, 2]) == 0  # unsupported type, default branch
    assert _to_int_flag([1, 2], allow_none=True) is None


def test_to_float_returns_none_on_garbage() -> None:
    from prevent_calculator.protocols.calculator_api import _to_float

    assert _to_float("not-a-number") is None
    assert _to_float({"k": "v"}) is None


def test_validate_ranges_flags_only_common_gates() -> None:
    """Only fields that gate every score (age, SBP, eGFR) hard-fail.
    BMI/TC/HDL are out-of-range here but should NOT appear — the
    equation layer nullifies the scores they affect on its own."""
    from prevent_calculator.protocols.calculator_api import _validate_ranges

    inp = PreventInput(
        sex=1, age=29, sbp=85, egfr=0,
        tc=125, hdl=15, bmi=18.0,
        dm=0, smoking=0, bptreat=0, statin=0,
    )
    errors = _validate_ranges(inp)
    assert set(errors.keys()) == {"age", "systolic_bp", "egfr"}


def test_validate_ranges_does_not_flag_out_of_range_bmi_tc_hdl() -> None:
    """A class-III-obesity / extreme-lipid patient should pass validation
    and let the equation layer return partial scores."""
    from prevent_calculator.protocols.calculator_api import _validate_ranges

    inp = PreventInput(
        sex=1, age=55, sbp=130, egfr=85,
        tc=400, hdl=10, bmi=42,
        dm=0, smoking=0, bptreat=0, statin=0,
    )
    assert _validate_ranges(inp) == {}


def test_validate_ranges_empty_when_in_range() -> None:
    from prevent_calculator.protocols.calculator_api import _validate_ranges

    inp = PreventInput(
        sex=1, age=55, sbp=130, egfr=85,
        tc=200, hdl=50, bmi=25,
        dm=0, smoking=0, bptreat=0, statin=0,
    )
    assert _validate_ranges(inp) == {}


def test_parse_inputs_reports_each_missing_field() -> None:
    parsed = _parse_inputs({})
    assert isinstance(parsed, dict)
    assert set(parsed["field_errors"].keys()) == {"sex", "age", "systolic_bp", "egfr"}


def test_post_calculate_returns_partial_scores_for_class_iii_obesity() -> None:
    """BMI ≥ 40 must not block CVD/ASCVD scoring (regression for the
    over-validation bug). HF scores will be None; CVD/ASCVD will compute."""
    api = _make_api(
        "POST",
        "/calculate",
        query_params={"patient_id": "p"},
        body={
            "sex": SEX_FEMALE,
            "age": 52,
            "total_cholesterol": 200,
            "hdl_cholesterol": 55,
            "systolic_bp": 130,
            "bmi": 42,  # class III obesity, out of AHA range
            "egfr": 85,
            "diabetes": 0,
            "smoking": 0,
            "bp_treatment": 0,
            "statin": 0,
        },
    )
    response = api.calculate()
    body = _extract_response_json(response)
    scores = body["scores"]
    # CVD/ASCVD should compute despite out-of-range BMI…
    assert isinstance(scores["risk_10yr_cvd"], (int, float))
    assert isinstance(scores["risk_10yr_ascvd"], (int, float))
    assert isinstance(scores["risk_30yr_cvd"], (int, float))
    assert isinstance(scores["risk_30yr_ascvd"], (int, float))
    # …and HF should be None because BMI is out of range.
    assert scores["risk_10yr_hf"] is None
    assert scores["risk_30yr_hf"] is None


def test_post_calculate_returns_partial_scores_for_extreme_dyslipidemia() -> None:
    """Out-of-range TC/HDL must not block HF scoring (HF only depends on BMI)."""
    api = _make_api(
        "POST",
        "/calculate",
        query_params={"patient_id": "p"},
        body={
            "sex": SEX_MALE,
            "age": 55,
            "total_cholesterol": 400,  # out of range
            "hdl_cholesterol": 10,     # out of range
            "systolic_bp": 130,
            "bmi": 28,
            "egfr": 85,
            "diabetes": 0,
            "smoking": 0,
            "bp_treatment": 0,
            "statin": 0,
        },
    )
    response = api.calculate()
    body = _extract_response_json(response)
    scores = body["scores"]
    # CVD/ASCVD should be None because lipids are out of range…
    assert scores["risk_10yr_cvd"] is None
    assert scores["risk_10yr_ascvd"] is None
    # …but HF should compute.
    assert isinstance(scores["risk_10yr_hf"], (int, float))


def test_post_calculate_common_gate_errors_still_return_400() -> None:
    """Age/SBP/eGFR out of range still hard-fail (every score depends on them)."""
    api = _make_api(
        "POST",
        "/calculate",
        query_params={"patient_id": "p"},
        body={
            "sex": 1, "age": 50,
            "systolic_bp": 1000,  # out of range
            "egfr": 85,
            "total_cholesterol": 200, "hdl_cholesterol": 50, "bmi": 25,
            "diabetes": 0, "smoking": 0, "bp_treatment": 0, "statin": 0,
        },
    )
    response = api.calculate()
    json_resp = next(e for e in response if hasattr(e, "status_code"))
    assert json_resp.status_code == 400
    body = _extract_response_json(response)
    assert "systolic_bp" in body["field_errors"]
    assert "bmi" not in body["field_errors"]
    assert "total_cholesterol" not in body["field_errors"]


def test_parse_inputs_missing_required_returns_field_errors() -> None:
    parsed = _parse_inputs({"sex": "1", "age": "55"})
    assert isinstance(parsed, dict)
    assert "field_errors" in parsed
    assert set(parsed["field_errors"].keys()) == {"systolic_bp", "egfr"}
    for msg in parsed["field_errors"].values():
        assert "required" in msg.lower()


def test_parse_inputs_truthy_string_flags() -> None:
    parsed = _parse_inputs(
        {
            "sex": "0",
            "age": "60",
            "systolic_bp": "130",
            "egfr": "85",
            "diabetes": "yes",
            "smoking": "true",
            "bp_treatment": "1",
            "statin": "0",
        }
    )
    assert isinstance(parsed, PreventInput)
    assert parsed.dm == 1
    assert parsed.smoking == 1
    assert parsed.bptreat == 1
    assert parsed.statin == 0


# -- _build_observation_effects ---------------------------------------------


def test_observation_effects_emitted_for_every_computed_score() -> None:
    """Every non-None score should yield an Observation effect, regardless of
    whether a LOINC mapping exists. Only None scores are skipped."""
    result = PreventResult(
        risk_10yr_cvd=12.34,
        risk_10yr_ascvd=8.0,
        risk_10yr_hf=3.5,
        risk_30yr_cvd=20.5,
        risk_30yr_ascvd=15.2,
        risk_30yr_hf=10.1,
    )
    effects = _build_observation_effects("patient-x", result)
    assert len(effects) == 6
    payloads = [json.loads(eff.payload) for eff in effects]
    # Two outputs have confirmed LOINC mappings.
    codings_attached = [p["data"].get("codings") for p in payloads if p["data"].get("codings")]
    assert len(codings_attached) == 2
    codes = {c[0]["code"] for c in codings_attached}
    assert codes == {"97506-9", "79423-0"}
    # Every effect persists as a laboratory observation in % units.
    assert all(p["data"]["category"] == "laboratory" for p in payloads)
    assert all(p["data"]["units"] == "%" for p in payloads)
    names = {p["data"]["name"] for p in payloads}
    assert names == {
        "PREVENT 10-year Total CVD risk",
        "PREVENT 10-year ASCVD risk",
        "PREVENT 10-year Heart Failure risk",
        "PREVENT 30-year Total CVD risk",
        "PREVENT 30-year ASCVD risk",
        "PREVENT 30-year Heart Failure risk",
    }


def test_observation_effects_only_emit_for_computed_scores() -> None:
    """Mixed result: only 10-year scores computed (e.g. age > 59)."""
    result = PreventResult(
        risk_10yr_cvd=12.34,
        risk_10yr_ascvd=8.0,
        risk_10yr_hf=3.5,
        risk_30yr_cvd=None,
        risk_30yr_ascvd=None,
        risk_30yr_hf=None,
    )
    effects = _build_observation_effects("patient-x", result)
    assert len(effects) == 3


def test_observation_effects_skip_none_scores() -> None:
    result = PreventResult(
        risk_10yr_cvd=None,
        risk_10yr_ascvd=None,
        risk_10yr_hf=None,
        risk_30yr_cvd=None,
        risk_30yr_ascvd=None,
        risk_30yr_hf=None,
    )
    effects = _build_observation_effects("patient-x", result)
    assert effects == []


# -- GET /calculator --------------------------------------------------------


def test_get_calculator_missing_patient_id_returns_400() -> None:
    api = _make_api("GET", "/calculator", query_params={})
    response = api.render_calculator()
    assert len(response) == 1
    assert response[0].status_code == 400


def test_get_calculator_renders_html_with_prefill() -> None:
    prefill = ChartPrefill(
        sex=ChartValue(value=1, clinical_date="2026-01-01"),
        age=ChartValue(value=45, clinical_date="2026-01-01"),
        total_cholesterol=ChartValue(value=200.0, clinical_date="2025-08-01"),
        hdl_cholesterol=ChartValue(value=60.0, clinical_date="2025-08-01"),
        systolic_bp=ChartValue(value=120.0, clinical_date="2026-04-01"),
        bmi=ChartValue(value=25.0, clinical_date="2026-04-01"),
        egfr=ChartValue(value=95.0, clinical_date="2025-08-01"),
        diabetes=ChartValue(value=1, clinical_date="2024-01-01"),
        smoking=ChartValue(value=0, clinical_date="2026-04-01"),
        bp_treatment=ChartValue(value=0, clinical_date="2026-04-01"),
        statin=ChartValue(value=0, clinical_date="2026-04-01"),
    )
    api = _make_api(
        "GET", "/calculator", query_params={"patient_id": "patient-1"}
    )
    captured: dict[str, Any] = {}

    def fake_render(template: str, context: dict[str, Any]) -> str:
        captured["template"] = template
        captured["context"] = context
        return f"<html>PREVENT CVD Risk Calculator patient_id={context['patient_id']} prefill={context['prefill_json']}</html>"

    with (
        patch(
            "prevent_calculator.protocols.calculator_api.fetch_chart_prefill",
            return_value=prefill,
        ),
        patch(
            "prevent_calculator.protocols.calculator_api.render_to_string",
            side_effect=fake_render,
        ),
    ):
        response = api.render_calculator()
    assert len(response) == 1
    raw = response[0].content
    html = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    assert response[0].status_code == 200
    assert "PREVENT CVD Risk Calculator" in html
    assert "patient-1" in html
    assert captured["template"] == "templates/calculator.html"
    assert captured["context"]["patient_id"] == "patient-1"
    prefill_payload = json.loads(captured["context"]["prefill_json"])
    assert prefill_payload["total_cholesterol"]["value"] == 200.0
    assert prefill_payload["hdl_cholesterol"]["value"] == 60.0
    assert prefill_payload["sex"]["value"] == 1


def test_get_calculator_returns_500_on_db_failure() -> None:
    api = _make_api(
        "GET", "/calculator", query_params={"patient_id": "patient-1"}
    )
    with (
        patch(
            "prevent_calculator.protocols.calculator_api.fetch_chart_prefill",
            side_effect=RuntimeError("db down"),
        ),
        patch("prevent_calculator.protocols.calculator_api.log"),
    ):
        response = api.render_calculator()
    assert len(response) == 1
    assert response[0].status_code == 500


# -- POST /calculate --------------------------------------------------------


def test_post_calculate_missing_patient_id_returns_400() -> None:
    api = _make_api("POST", "/calculate", query_params={}, body={})
    response = api.calculate()
    assert response[0].status_code == 400


def test_post_calculate_invalid_json_returns_400() -> None:
    api = _make_api("POST", "/calculate", query_params={"patient_id": "p"})
    response = api.calculate()
    assert response[0].status_code == 400


def test_post_calculate_missing_required_inputs_returns_400() -> None:
    api = _make_api(
        "POST",
        "/calculate",
        query_params={"patient_id": "p"},
        body={"sex": "1"},
    )
    response = api.calculate()
    assert response[0].status_code == 400


def test_post_calculate_valid_body_returns_scores_and_observations() -> None:
    api = _make_api(
        "POST",
        "/calculate",
        query_params={"patient_id": "patient-1"},
        body={
            "sex": SEX_FEMALE,
            "age": 45,
            "total_cholesterol": 200,
            "hdl_cholesterol": 60,
            "systolic_bp": 120,
            "bmi": 25,
            "egfr": 95,
            "diabetes": 1,
            "smoking": 0,
            "bp_treatment": 0,
            "statin": 0,
        },
    )
    response = api.calculate()

    body = _extract_response_json(response)
    scores = body["scores"]
    for key in (
        "risk_10yr_cvd",
        "risk_10yr_ascvd",
        "risk_10yr_hf",
        "risk_30yr_cvd",
        "risk_30yr_ascvd",
        "risk_30yr_hf",
    ):
        assert key in scores
    assert _count_observation_effects(response) == 6  # all scores save as labs


def test_post_calculate_male_75yo_skips_30yr() -> None:
    api = _make_api(
        "POST",
        "/calculate",
        query_params={"patient_id": "p"},
        body={
            "sex": SEX_MALE,
            "age": 75,
            "total_cholesterol": 240,
            "hdl_cholesterol": 90,
            "systolic_bp": 130,
            "bmi": 30,
            "egfr": 105,
            "diabetes": 0,
            "smoking": 0,
            "bp_treatment": 1,
            "statin": 1,
        },
    )
    response = api.calculate()
    body = _extract_response_json(response)
    scores = body["scores"]
    assert scores["risk_30yr_cvd"] is None
    assert scores["risk_30yr_ascvd"] is None
    assert scores["risk_30yr_hf"] is None
    assert scores["risk_10yr_cvd"] is not None


def test_post_calculate_with_enhanced_inputs_uses_full_model() -> None:
    body = {
        "sex": SEX_FEMALE,
        "age": 50,
        "total_cholesterol": 220,
        "hdl_cholesterol": 45,
        "systolic_bp": 140,
        "bmi": 28,
        "egfr": 80,
        "diabetes": 1,
        "smoking": 0,
        "bp_treatment": 0,
        "statin": 0,
        "hba1c": 7.2,
        "uacr": 35,
        "sdi_decile": 6,
    }
    api = _make_api("POST", "/calculate", query_params={"patient_id": "p"}, body=body)
    response = api.calculate()
    api_body = _extract_response_json(response)
    assert api_body.get("model_used") == "full"
    assert api_body["scores"]["risk_10yr_cvd"] is not None


def test_post_calculate_save_inputs_emits_input_observations() -> None:
    body = {
        "sex": SEX_MALE,
        "age": 55,
        "total_cholesterol": 200,
        "hdl_cholesterol": 50,
        "systolic_bp": 130,
        "bmi": 26,
        "egfr": 85,
        "diabetes": 0,
        "smoking": 0,
        "bp_treatment": 0,
        "statin": 0,
        "hba1c": 5.6,
        "save_inputs_to_chart": True,
    }
    api = _make_api("POST", "/calculate", query_params={"patient_id": "p"}, body=body)
    response = api.calculate()
    api_body = _extract_response_json(response)
    # 6 score observations + 5 simple input observations (TC, HDL, BMI,
    # eGFR, HbA1c). UACR not supplied → not saved. SBP also not saved
    # because the patient has no prior ``blood_pressure`` observation
    # to pair the new systolic with — the SBP save path needs the
    # existing diastolic to emit a Canvas-style composite panel and
    # refuses to fabricate one.
    assert _count_observation_effects(response) == 11
    assert len(api_body.get("inputs_saved", [])) == 5


# -- _input_save_label fallback paths --------------------------------------


def test_input_save_label_returns_name_from_valid_payload() -> None:
    effect = SimpleNamespace(payload='{"name": "Hemoglobin A1c"}')
    assert _input_save_label(effect) == "Hemoglobin A1c"


def test_input_save_label_returns_generic_for_none_payload() -> None:
    effect = SimpleNamespace(payload=None)
    assert _input_save_label(effect) == "input"


def test_input_save_label_falls_back_when_payload_lacks_get_method() -> None:
    """If a future SDK upgrade ships ``effect.payload`` as something other
    than a JSON string (e.g. a protobuf message object), ``decoded.get``
    would raise ``AttributeError``. The fallback must absorb it instead
    of 500'ing the POST response."""
    # A bare integer survives ``json.loads`` (parses as int) but has no
    # ``.get`` method → triggers AttributeError on the next line.
    effect = SimpleNamespace(payload="42")
    assert _input_save_label(effect) == "input"


def test_input_save_label_falls_back_on_invalid_json() -> None:
    effect = SimpleNamespace(payload="not json")
    assert _input_save_label(effect) == "input"


# -- _safe_json_for_script (XSS hardening) ----------------------------------


def test_safe_json_escapes_script_close_tag() -> None:
    """``</script>`` inside a JSON value must not close the surrounding
    ``<script>`` block when injected into the modal template."""
    out = _safe_json_for_script({"x": "</script><img onerror=alert(1)>"})
    assert "</script>" not in out
    assert "<" not in out
    assert ">" not in out
    # Round-trips through JSON.parse intact (Python's json.loads accepts
    # the same escape sequences JavaScript does).
    assert json.loads(out) == {"x": "</script><img onerror=alert(1)>"}


def test_safe_json_escapes_ampersand() -> None:
    """``&`` could otherwise begin an HTML entity inside a string literal."""
    out = _safe_json_for_script({"q": "a & b"})
    assert "&" not in out
    assert json.loads(out) == {"q": "a & b"}


def test_safe_json_escapes_js_line_and_paragraph_separators() -> None:
    """U+2028 / U+2029 terminate JavaScript string literals even though
    they're legal in JSON; encoding as ``\\u2028`` / ``\\u2029`` keeps
    the embedded JSON valid as a JS literal."""
    out = _safe_json_for_script({"a": "line\u2028sep", "b": "para\u2029sep"})
    assert "\u2028" not in out
    assert "\u2029" not in out
    parsed = json.loads(out)
    assert parsed == {"a": "line\u2028sep", "b": "para\u2029sep"}


def test_safe_json_preserves_normal_unicode_in_chart_data() -> None:
    """Normal Unicode (e.g. m² in unit strings) is preserved."""
    out = _safe_json_for_script({"units": "kg/m²"})
    assert json.loads(out) == {"units": "kg/m²"}


# -- SBP composite-panel save flow ------------------------------------------


def test_extract_diastolic_handles_standard_and_malformed_values() -> None:
    assert _extract_diastolic_from_bp_value("128/82") == "82"
    assert _extract_diastolic_from_bp_value("  120 / 70 ") == "70"
    assert _extract_diastolic_from_bp_value("120") is None
    assert _extract_diastolic_from_bp_value("") is None
    assert _extract_diastolic_from_bp_value(None) is None
    assert _extract_diastolic_from_bp_value("128/") is None


def test_save_systolic_bp_as_panel_emits_composite_when_prior_bp_exists() -> None:
    """SBP edits get persisted as a Canvas-style ``blood_pressure`` row
    with value ``<new_systolic>/<existing_diastolic>``, LOINC 85354-9."""
    prior_bp = SimpleNamespace(value="128/82")
    now = dt.datetime(2026, 5, 20, 12, 0, tzinfo=dt.timezone.utc)
    with patch(
        "prevent_calculator.protocols.calculator_api._latest_observation_by_name",
        return_value=prior_bp,
    ):
        effect = _save_systolic_bp_as_panel("p1", 135.0, now)
    assert effect is not None
    payload = json.loads(effect.payload)["data"]
    assert payload["name"] == "blood_pressure"
    assert payload["value"] == "135/82"
    assert payload["units"] == "mmHg"
    assert payload["category"] == "vital-signs"
    assert payload["codings"][0]["code"] == "85354-9"


def test_save_systolic_bp_as_panel_skips_when_no_prior_bp_observation() -> None:
    """Without a prior BP observation we can't preserve the diastolic
    half — saving a standalone systolic would put the value outside
    the patient's normal BP history, so the resolver returns None."""
    with patch(
        "prevent_calculator.protocols.calculator_api._latest_observation_by_name",
        return_value=None,
    ):
        effect = _save_systolic_bp_as_panel("p1", 135.0, dt.datetime.now(dt.timezone.utc))
    assert effect is None


def test_save_systolic_bp_as_panel_skips_when_prior_bp_has_no_diastolic() -> None:
    bad_bp = SimpleNamespace(value="135")  # no slash, no diastolic
    with patch(
        "prevent_calculator.protocols.calculator_api._latest_observation_by_name",
        return_value=bad_bp,
    ):
        effect = _save_systolic_bp_as_panel("p1", 140.0, dt.datetime.now(dt.timezone.utc))
    assert effect is None


def test_build_input_effects_persists_sbp_as_panel_when_prior_bp_exists() -> None:
    """End-to-end: ``_build_input_observation_effects`` runs the SBP
    composite-save path when the clinician's modified_fields includes
    systolic_bp AND the patient has a prior BP observation."""
    parsed = PreventInput(
        sex=SEX_FEMALE, age=50, tc=200.0, hdl=55.0, sbp=140.0, dm=0,
        smoking=0, bmi=26, egfr=85, bptreat=0, statin=0,
    )
    prior_bp = SimpleNamespace(value="118/76")
    with patch(
        "prevent_calculator.protocols.calculator_api._latest_observation_by_name",
        return_value=prior_bp,
    ):
        effects = _build_input_observation_effects(
            "p1", parsed, modified_fields={"systolic_bp"}
        )
    # Only SBP was in modified_fields → exactly one effect, the composite BP
    assert len(effects) == 1
    payload = json.loads(effects[0].payload)["data"]
    assert payload["name"] == "blood_pressure"
    assert payload["value"] == "140/76"


def test_post_calculate_save_inputs_only_persists_modified_fields() -> None:
    """When the client sends ``modified_fields``, only those numeric
    inputs get persisted — the rest are assumed to match the chart
    pre-fill and aren't duplicated."""
    body = {
        "sex": SEX_FEMALE,
        "age": 50,
        "total_cholesterol": 200,
        "hdl_cholesterol": 55,
        "systolic_bp": 130,
        "bmi": 26,
        "egfr": 85,
        "diabetes": 0,
        "smoking": 0,
        "bp_treatment": 0,
        "statin": 0,
        "save_inputs_to_chart": True,
        # Clinician overrode TC and BMI; everything else matched pre-fill.
        "modified_fields": ["total_cholesterol", "bmi"],
    }
    api = _make_api("POST", "/calculate", query_params={"patient_id": "p"}, body=body)
    response = api.calculate()
    api_body = _extract_response_json(response)
    # 6 score observations + 2 input observations (TC and BMI only)
    assert _count_observation_effects(response) == 8
    assert len(api_body.get("inputs_saved", [])) == 2


def test_post_calculate_save_inputs_empty_modified_fields_persists_nothing() -> None:
    """An explicit empty list means the clinician didn't override any
    field; we save zero input Observations even though the checkbox is on."""
    body = {
        "sex": SEX_FEMALE,
        "age": 50,
        "total_cholesterol": 200,
        "hdl_cholesterol": 55,
        "systolic_bp": 130,
        "bmi": 26,
        "egfr": 85,
        "diabetes": 0,
        "smoking": 0,
        "bp_treatment": 0,
        "statin": 0,
        "save_inputs_to_chart": True,
        "modified_fields": [],
    }
    api = _make_api("POST", "/calculate", query_params={"patient_id": "p"}, body=body)
    response = api.calculate()
    api_body = _extract_response_json(response)
    assert _count_observation_effects(response) == 6  # scores only
    assert api_body.get("inputs_saved", []) == []


def test_post_calculate_save_inputs_default_off_does_not_emit_input_obs() -> None:
    body = {
        "sex": SEX_MALE,
        "age": 55,
        "total_cholesterol": 200,
        "hdl_cholesterol": 50,
        "systolic_bp": 130,
        "bmi": 26,
        "egfr": 85,
        "diabetes": 0,
        "smoking": 0,
        "bp_treatment": 0,
        "statin": 0,
    }
    api = _make_api("POST", "/calculate", query_params={"patient_id": "p"}, body=body)
    response = api.calculate()
    api_body = _extract_response_json(response)
    # Only score observations
    assert _count_observation_effects(response) == 6
    assert api_body.get("inputs_saved", []) == []


def test_post_calculate_score_matches_direct_call() -> None:
    """API and direct call should produce identical scores for the same inputs."""
    body = {
        "sex": SEX_FEMALE,
        "age": 50,
        "total_cholesterol": 220,
        "hdl_cholesterol": 45,
        "systolic_bp": 140,
        "bmi": 28,
        "egfr": 80,
        "diabetes": 0,
        "smoking": 1,
        "bp_treatment": 0,
        "statin": 0,
    }
    direct = compute_prevent_base(
        PreventInput(
            sex=int(body["sex"]),
            age=float(body["age"]),
            tc=float(body["total_cholesterol"]),
            hdl=float(body["hdl_cholesterol"]),
            sbp=float(body["systolic_bp"]),
            dm=int(body["diabetes"]),
            smoking=int(body["smoking"]),
            bmi=float(body["bmi"]),
            egfr=float(body["egfr"]),
            bptreat=int(body["bp_treatment"]),
            statin=int(body["statin"]),
        )
    )

    api = _make_api(
        "POST",
        "/calculate",
        query_params={"patient_id": "p"},
        body=body,
    )
    response = api.calculate()
    api_body = _extract_response_json(response)
    api_scores = api_body["scores"]
    assert api_scores["risk_10yr_cvd"] == direct.risk_10yr_cvd
    assert api_scores["risk_10yr_ascvd"] == direct.risk_10yr_ascvd
