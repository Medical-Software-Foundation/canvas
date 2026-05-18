"""Tests for the Phase D single-command section registry (pass 1 + pass 2)."""

from datetime import date

from canvas_sdk.commands import FollowUpCommand, PlanCommand, TaskCommand

from nutrition_charting.data.single_command_sections import (
    RECOMMENDED_LAB_OPTIONS,
    SINGLE_COMMAND_SECTIONS,
    _build_counseling_plan_kwargs,
    _build_followup_kwargs,
    _build_monitor_team_meeting_kwargs,
    _build_recommended_labs_kwargs,
    _build_recommended_supplementation_kwargs,
    _build_requirements_plan_kwargs,
    _counseling_emit_ready,
    _followup_emit_ready,
    _is_truthy,
    _monitor_team_meeting_emit_ready,
    _parse_date,
    _recommended_labs_emit_ready,
    _recommended_supplementation_emit_ready,
    _requirements_emit_ready,
    get_section,
)


def test_registry_includes_all_phase_d_sections() -> None:
    assert set(SINGLE_COMMAND_SECTIONS) == {
        "estimated_nutrition_requirements",
        "counseling_narrative",
        "follow_up_appointment",
        "recommended_labs",
        "recommended_supplementation",
        "monitor_team_meeting",
    }


def test_get_section_returns_none_for_unknown() -> None:
    assert get_section("nope") is None


def test_get_section_returns_metadata() -> None:
    section = get_section("estimated_nutrition_requirements")
    assert section is not None
    assert section["command_class"] is PlanCommand
    assert any(field[0] == "calories" for field in section["fields"])


def test_followup_section_uses_followup_command() -> None:
    section = get_section("follow_up_appointment")
    assert section is not None
    assert section["command_class"] is FollowUpCommand


# ---- _parse_date ----

def test_parse_date_round_trips_iso_string() -> None:
    assert _parse_date("2026-06-15") == date(2026, 6, 15)


def test_parse_date_passes_through_date_objects() -> None:
    d = date(2026, 6, 15)
    assert _parse_date(d) == d


def test_parse_date_returns_none_for_invalid_input() -> None:
    assert _parse_date("") is None
    assert _parse_date(None) is None
    assert _parse_date("not-a-date") is None


# ---- Requirements builder ----

def test_requirements_builder_formats_filled_fields() -> None:
    kwargs = _build_requirements_plan_kwargs({
        "calories": "1800",
        "protein": "75",
        "carbohydrates": "225",
        "fluid": "2000",
    })
    narrative = kwargs["narrative"]
    assert narrative.startswith("Estimated Nutrition Requirements")
    assert "Calories: 1800 kcal/day" in narrative
    assert "Protein: 75 g/day" in narrative
    assert "Carbohydrates: 225 g/day" in narrative
    assert "Fluid: 2000 mL/day" in narrative


def test_requirements_builder_skips_blank_fields() -> None:
    kwargs = _build_requirements_plan_kwargs({"calories": "1800", "protein": "", "fluid": None})
    narrative = kwargs["narrative"]
    assert "Calories" in narrative
    assert "Protein" not in narrative
    assert "Fluid" not in narrative


def test_requirements_builder_returns_empty_when_all_blank() -> None:
    assert _build_requirements_plan_kwargs({"calories": "", "protein": "", "carbohydrates": "", "fluid": ""}) == {}
    assert _build_requirements_plan_kwargs({}) == {}


def test_requirements_emit_ready_tracks_builder_output() -> None:
    assert _requirements_emit_ready({"calories": "1800"})
    assert not _requirements_emit_ready({})
    assert not _requirements_emit_ready({"calories": ""})


# ---- Follow-up builder ----

def test_followup_builder_returns_kwargs_with_date_only() -> None:
    kwargs = _build_followup_kwargs({"follow_up_date": "2026-06-15"})
    assert kwargs == {"requested_date": date(2026, 6, 15)}


def test_followup_builder_includes_comment_when_present() -> None:
    kwargs = _build_followup_kwargs({
        "follow_up_date": "2026-06-15",
        "follow_up_comment": "  Discuss labs ",
    })
    assert kwargs["requested_date"] == date(2026, 6, 15)
    assert kwargs["comment"] == "Discuss labs"


def test_followup_builder_skips_blank_comment() -> None:
    kwargs = _build_followup_kwargs({"follow_up_date": "2026-06-15", "follow_up_comment": "  "})
    assert "comment" not in kwargs


def test_followup_builder_returns_empty_without_date() -> None:
    assert _build_followup_kwargs({}) == {}
    assert _build_followup_kwargs({"follow_up_date": None}) == {}
    assert _build_followup_kwargs({"follow_up_date": "bogus"}) == {}


def test_followup_emit_ready_requires_a_parseable_date() -> None:
    assert _followup_emit_ready({"follow_up_date": "2026-06-15"})
    assert not _followup_emit_ready({"follow_up_date": ""})
    assert not _followup_emit_ready({"follow_up_date": "notadate"})


# ---- Pass 2: Counseling narrative ----

def test_counseling_section_uses_plan_command() -> None:
    section = get_section("counseling_narrative")
    assert section is not None
    assert section["command_class"] is PlanCommand


def test_counseling_builder_wraps_text_in_titled_narrative() -> None:
    kwargs = _build_counseling_plan_kwargs({"counseling_narrative": "Discussed portion control."})
    assert kwargs["narrative"].startswith("Counseling\n")
    assert "Discussed portion control." in kwargs["narrative"]


def test_counseling_builder_returns_empty_when_blank() -> None:
    assert _build_counseling_plan_kwargs({"counseling_narrative": ""}) == {}
    assert _build_counseling_plan_kwargs({}) == {}


def test_counseling_emit_ready_tracks_text() -> None:
    assert _counseling_emit_ready({"counseling_narrative": "x"})
    assert not _counseling_emit_ready({"counseling_narrative": "   "})


# ---- Pass 2: Recommended labs ----

def test_recommended_labs_section_uses_plan_command() -> None:
    section = get_section("recommended_labs")
    assert section is not None
    assert section["command_class"] is PlanCommand
    assert section["checklist_options"] == RECOMMENDED_LAB_OPTIONS


def test_recommended_labs_builder_resolves_canonical_keys_to_labels() -> None:
    kwargs = _build_recommended_labs_kwargs({"selected": ["a1c", "lipid_panel"]})
    assert kwargs["narrative"].startswith("Recommended Labs\n")
    assert "- A1c / HbA1c" in kwargs["narrative"]
    assert "- Lipid panel" in kwargs["narrative"]


def test_recommended_labs_builder_appends_other_lines() -> None:
    kwargs = _build_recommended_labs_kwargs({
        "selected": ["a1c"],
        "other": "TSH\nUric Acid",
    })
    assert "- A1c / HbA1c" in kwargs["narrative"]
    assert "- TSH" in kwargs["narrative"]
    assert "- Uric Acid" in kwargs["narrative"]


def test_recommended_labs_builder_passes_through_unknown_keys_as_labels() -> None:
    """If a future canonical key is added in the front-end before the registry
    catches up, we still render it instead of silently dropping it."""
    kwargs = _build_recommended_labs_kwargs({"selected": ["new_panel"]})
    assert "- new_panel" in kwargs["narrative"]


def test_recommended_labs_builder_accepts_other_as_list() -> None:
    kwargs = _build_recommended_labs_kwargs({"other": ["TSH", "  ", "Cortisol"]})
    assert "- TSH" in kwargs["narrative"]
    assert "- Cortisol" in kwargs["narrative"]
    assert kwargs["narrative"].count("\n-") == 2  # blank entry dropped


def test_recommended_labs_builder_returns_empty_when_no_inputs() -> None:
    assert _build_recommended_labs_kwargs({"selected": [], "other": ""}) == {}
    assert _build_recommended_labs_kwargs({}) == {}


def test_recommended_labs_emit_ready_tracks_builder() -> None:
    assert _recommended_labs_emit_ready({"selected": ["a1c"]})
    assert not _recommended_labs_emit_ready({"selected": [], "other": ""})


# ---- Pass 2: Recommended supplementation ----

def test_supplementation_builder_wraps_in_titled_narrative() -> None:
    kwargs = _build_recommended_supplementation_kwargs(
        {"supplementation": "Vitamin D 2000 IU daily"}
    )
    assert kwargs["narrative"].startswith("Recommended Supplementation\n")
    assert "Vitamin D 2000 IU daily" in kwargs["narrative"]


def test_supplementation_builder_returns_empty_when_blank() -> None:
    assert _build_recommended_supplementation_kwargs({"supplementation": ""}) == {}
    assert _build_recommended_supplementation_kwargs({}) == {}


def test_supplementation_emit_ready_tracks_text() -> None:
    assert _recommended_supplementation_emit_ready({"supplementation": "x"})
    assert not _recommended_supplementation_emit_ready({"supplementation": ""})


# ---- Pass 2: Monitor at team meeting ----

def test_monitor_section_uses_task_command() -> None:
    section = get_section("monitor_team_meeting")
    assert section is not None
    assert section["command_class"] is TaskCommand


def test_monitor_builder_emits_task_when_checkbox_on() -> None:
    from canvas_sdk.commands.commands.task import AssigneeType

    kwargs = _build_monitor_team_meeting_kwargs({"monitor": True})
    assert kwargs["title"]
    assert kwargs["assign_to"] == {"to": AssigneeType.UNASSIGNED}


def test_monitor_builder_includes_comment_when_present() -> None:
    kwargs = _build_monitor_team_meeting_kwargs({"monitor": True, "comment": "  flag glycemic control  "})
    assert kwargs["comment"] == "flag glycemic control"


def test_monitor_builder_skips_blank_comment() -> None:
    kwargs = _build_monitor_team_meeting_kwargs({"monitor": True, "comment": " "})
    assert "comment" not in kwargs


def test_monitor_builder_returns_empty_when_checkbox_off() -> None:
    assert _build_monitor_team_meeting_kwargs({"monitor": False}) == {}
    assert _build_monitor_team_meeting_kwargs({"monitor": "off"}) == {}
    assert _build_monitor_team_meeting_kwargs({}) == {}


def test_monitor_emit_ready_tracks_checkbox_state() -> None:
    assert _monitor_team_meeting_emit_ready({"monitor": True})
    assert _monitor_team_meeting_emit_ready({"monitor": "true"})
    assert not _monitor_team_meeting_emit_ready({"monitor": False})
    assert not _monitor_team_meeting_emit_ready({})


def test_is_truthy_handles_form_encodings() -> None:
    assert _is_truthy(True)
    assert _is_truthy("on")
    assert _is_truthy("true")
    assert _is_truthy("Yes")
    assert _is_truthy("1")
    assert _is_truthy(1)
    assert not _is_truthy(False)
    assert not _is_truthy("")
    assert not _is_truthy(None)
    assert not _is_truthy("nope")
