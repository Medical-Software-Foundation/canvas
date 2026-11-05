"""Tests for the single-command section abstractions (Vitals)."""
from __future__ import annotations

from canvas_sdk.commands import VitalsCommand

from intake_chart_app.data.single_command_sections import VitalsSection


def test_vitals_section_id_is_stable():
    assert VitalsSection().section_id == "vitals"


def test_vitals_command_class():
    assert VitalsSection().command_class is VitalsCommand


def test_is_emit_ready_false_for_empty_draft():
    section = VitalsSection()
    assert section.is_emit_ready({}) is False
    assert section.is_emit_ready({"height": "", "weight_lbs": None}) is False
    assert section.is_emit_ready({"pulse": "  "}) is False


def test_is_emit_ready_true_for_any_non_empty_value():
    assert VitalsSection().is_emit_ready({"pulse": 72}) is True
    assert VitalsSection().is_emit_ready({"body_temperature": 98.6}) is True
    assert VitalsSection().is_emit_ready({"height": "70"}) is True


def test_build_kwargs_omits_empty_fields():
    draft = {
        "blood_pressure_systole": 120,
        "blood_pressure_diastole": 80,
        "pulse": 72,
        "height": "",
        "weight_lbs": None,
        "body_temperature": "",
    }
    kwargs = VitalsSection().build_kwargs(draft)
    assert kwargs == {
        "blood_pressure_systole": 120,
        "blood_pressure_diastole": 80,
        "pulse": 72,
    }


def test_build_kwargs_coerces_int_fields_from_strings():
    """The HTML form posts every field as a string; int fields must coerce."""
    draft = {
        "height": "70",
        "weight_lbs": "165",
        "blood_pressure_systole": "118",
        "blood_pressure_diastole": "76",
        "pulse": "68",
        "respiration_rate": "14",
        "oxygen_saturation": "98",
    }
    kwargs = VitalsSection().build_kwargs(draft)
    for f in (
        "height", "weight_lbs",
        "blood_pressure_systole", "blood_pressure_diastole",
        "pulse", "respiration_rate", "oxygen_saturation",
    ):
        assert kwargs[f] == int(draft[f])
        assert isinstance(kwargs[f], int)


def test_build_kwargs_coerces_float_for_body_temperature():
    draft = {"body_temperature": "98.6"}
    kwargs = VitalsSection().build_kwargs(draft)
    assert kwargs == {"body_temperature": 98.6}
    assert isinstance(kwargs["body_temperature"], float)


def test_build_kwargs_rounds_decimal_int_inputs():
    """The Vitals form uses ``step=0.1`` on numeric inputs so the MA can type
    e.g. 167.5 lbs; VitalsCommand wants ints, so we round."""
    draft = {"weight_lbs": "167.4", "pulse": "72.6"}
    kwargs = VitalsSection().build_kwargs(draft)
    assert kwargs == {"weight_lbs": 167, "pulse": 73}


def test_build_kwargs_drops_unparseable_numeric_values():
    """A garbage form value (e.g. ``'not a number'``) should be dropped, not
    passed through to VitalsCommand where it would fail validation."""
    draft = {"pulse": "not a number", "height": 70}
    kwargs = VitalsSection().build_kwargs(draft)
    assert kwargs == {"height": 70}


def test_build_kwargs_ignores_unknown_fields():
    draft = {"pulse": 72, "extra": "ignore-me"}
    kwargs = VitalsSection().build_kwargs(draft)
    assert kwargs == {"pulse": 72}


def test_field_names_match_vitals_command_signature():
    """Defensive: every VitalsSection field must be a real VitalsCommand
    parameter. Catches typos when SDK field names drift."""
    import inspect
    valid = set(inspect.signature(VitalsCommand).parameters)
    section_fields = set(VitalsSection().all_fields())
    assert section_fields <= valid, (
        f"VitalsSection field(s) not in VitalsCommand: {section_fields - valid}"
    )


# ---------------------------------------------------------------------------
# SocialHistorySection — ATOD questionnaire
# ---------------------------------------------------------------------------


def test_social_history_section_id_is_stable():
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    assert SocialHistorySection().section_id == "social_history"


def test_social_history_command_class_is_structured_assessment():
    from canvas_sdk.commands import StructuredAssessmentCommand
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    assert SocialHistorySection().command_class is StructuredAssessmentCommand


def test_social_history_questionnaire_code_is_atod_v1():
    """The section binds to the bundled questionnaire by INTERNAL code; the
    dispatch layer resolves the row's UUID at commit time."""
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    assert SocialHistorySection().questionnaire_code == "INTAKE_ATOD_V1"


def test_social_history_is_emit_ready_false_for_empty_draft():
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    section = SocialHistorySection()
    assert section.is_emit_ready({}) is False
    assert section.is_emit_ready({"alcohol": "", "tobacco": "", "drugs": "", "details": ""}) is False
    assert section.is_emit_ready({"details": "   "}) is False


def test_social_history_is_emit_ready_true_when_any_radio_picked():
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    section = SocialHistorySection()
    assert section.is_emit_ready({"alcohol": "former"}) is True
    assert section.is_emit_ready({"tobacco": "never"}) is True
    assert section.is_emit_ready({"drugs": "current"}) is True


def test_social_history_is_emit_ready_true_when_only_details_filled():
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    assert SocialHistorySection().is_emit_ready({"details": "Note text"}) is True


def test_social_history_build_kwargs_returns_question_code_map():
    """The dispatch layer needs the four answers keyed by the bundled
    questionnaire's question code so it can find the matching
    ``cmd.questions[i]`` and call add_response()."""
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    draft = {
        "alcohol": "former",
        "tobacco": "never",
        "drugs": "never",
        "details": "Stopped drinking in 2019.",
    }
    kwargs = SocialHistorySection().build_kwargs(draft)
    assert kwargs == {
        "answers": {
            "INTAKE_ATOD_ALCOHOL": "former",
            "INTAKE_ATOD_TOBACCO": "never",
            "INTAKE_ATOD_DRUGS": "never",
            "INTAKE_ATOD_DETAILS": "Stopped drinking in 2019.",
        },
    }


def test_social_history_build_kwargs_omits_empty_fields():
    """Empty / whitespace-only inputs are dropped from the answers map so the
    reconciler doesn't waste an add_response call (and so an invalid empty
    radio doesn't trigger the SDK's option validation)."""
    from intake_chart_app.data.single_command_sections import SocialHistorySection
    draft = {"alcohol": "former", "tobacco": "", "drugs": "  ", "details": ""}
    kwargs = SocialHistorySection().build_kwargs(draft)
    assert kwargs == {"answers": {"INTAKE_ATOD_ALCOHOL": "former"}}


def test_social_history_section_registered_in_sections():
    """Adding SocialHistorySection to SECTIONS is what hooks it into
    IntakeAPI.commit's loop."""
    from intake_chart_app.data.single_command_sections import SECTIONS, SocialHistorySection
    assert any(isinstance(s, SocialHistorySection) for s in SECTIONS)
