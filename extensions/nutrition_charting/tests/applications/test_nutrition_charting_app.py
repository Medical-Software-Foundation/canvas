"""Tests for NutritionChartingApp gating + handle output (Phase A + B)."""

from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.handlers.application import NoteApplication
from django.db import DatabaseError

from nutrition_charting.applications.nutrition_charting_app import (
    NutritionChartingApp,
    _render_chart_review_section,
    _render_page,
    is_nutrition_note,
)


def _mock_event(*, note_id: int | str | None = 7, patient_id: str = "patient-abc") -> MagicMock:
    event = MagicMock()
    event.context = {"note_id": note_id, "patient_id": patient_id}
    event.target.id = patient_id
    return event


def _mock_note(*, id_: str = "note-uuid-1", note_type_name: str = "Nutrition") -> MagicMock:
    note = MagicMock()
    note.id = id_
    note.note_type_version.name = note_type_name
    return note


# ---- Class wiring & gating ----

def test_app_inherits_note_application() -> None:
    assert issubclass(NutritionChartingApp, NoteApplication)


def test_app_identifier_and_name() -> None:
    assert NutritionChartingApp.NAME == "Nutrition"
    assert NutritionChartingApp.IDENTIFIER == "nutrition_charting__nutrition_charting"


@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_visible_true_for_plain_nutrition_note_type(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note(
        note_type_name="Nutrition"
    )

    assert NutritionChartingApp(event=_mock_event()).visible() is True


@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_visible_true_for_nutrition_visit_note_type(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note(
        note_type_name="Nutrition Follow-up"
    )

    assert NutritionChartingApp(event=_mock_event()).visible() is True


@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_visible_is_case_insensitive(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note(
        note_type_name="NUTRITION INITIAL"
    )

    assert NutritionChartingApp(event=_mock_event()).visible() is True


@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_visible_false_for_non_nutrition_note_type(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note(
        note_type_name="Office Visit"
    )

    assert NutritionChartingApp(event=_mock_event()).visible() is False


def test_visible_false_when_note_id_missing() -> None:
    assert NutritionChartingApp(event=_mock_event(note_id=None)).visible() is False


@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_visible_false_when_note_does_not_exist(mock_note_cls: MagicMock) -> None:
    class DoesNotExist(Exception):
        pass

    mock_note_cls.DoesNotExist = DoesNotExist
    mock_note_cls.objects.select_related.return_value.get.side_effect = DoesNotExist()

    assert NutritionChartingApp(event=_mock_event()).visible() is False


def test_is_nutrition_note_returns_false_for_blank_id() -> None:
    assert is_nutrition_note(None) is False
    assert is_nutrition_note("") is False
    assert is_nutrition_note(0) is False


# ---- handle() / page rendering ----

@patch("nutrition_charting.applications.nutrition_charting_app.build_chart_review")
@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_handle_returns_launch_modal_targeting_note(
    mock_note_cls: MagicMock, mock_build: MagicMock,
) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note(
        id_="note-uuid-xyz", note_type_name="Nutrition"
    )
    mock_build.return_value = {"missing": True, "patient_id": "pat-1"}

    effects = NutritionChartingApp(event=_mock_event(patient_id="pat-1")).handle()

    assert len(effects) == 1
    assert "modal" in effects[0].payload.lower() or "note" in effects[0].payload.lower()


@patch("nutrition_charting.applications.nutrition_charting_app.build_chart_review")
@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_handle_html_includes_note_uuid_and_patient_id(
    mock_note_cls: MagicMock, mock_build: MagicMock,
) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note(
        id_="note-uuid-xyz", note_type_name="Nutrition Initial"
    )
    mock_build.return_value = {
        "missing": False, "patient_id": "pat-9",
        "age": 36, "sex": "F",
        "anthropometrics": {"height": "67", "weight": "165"},
        "pmh": [], "allergies": [], "labs": [], "medications": [],
    }

    effects = NutritionChartingApp(event=_mock_event(patient_id="pat-9")).handle()
    payload = effects[0].payload

    assert "note-uuid-xyz" in payload
    assert "pat-9" in payload
    assert "Nutrition Initial" in payload


@patch("nutrition_charting.applications.nutrition_charting_app.build_chart_review")
@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_handle_falls_back_safely_when_chart_review_raises(
    mock_note_cls: MagicMock, mock_build: MagicMock,
) -> None:
    """Transient DB errors during chart extraction must not kill the tab —
    the modal still renders with a 'patient chart not loaded' message."""
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note()
    mock_build.side_effect = DatabaseError("DB blew up")

    effects = NutritionChartingApp(event=_mock_event(patient_id="pat-1")).handle()

    assert len(effects) == 1
    assert "Nutrition" in effects[0].payload


@patch("nutrition_charting.applications.nutrition_charting_app.build_chart_review")
@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_handle_propagates_non_db_errors_so_sentry_sees_them(
    mock_note_cls: MagicMock, mock_build: MagicMock,
) -> None:
    """A bug like AttributeError after a model field rename must NOT be
    swallowed by `_safe_chart_review`'s narrowed catch — it has to bubble
    up so Sentry's logging integration captures it."""
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note()
    mock_build.side_effect = AttributeError("renamed field")

    with pytest.raises(AttributeError):
        NutritionChartingApp(event=_mock_event(patient_id="pat-1")).handle()


# ---- _render_chart_review_section ----

def test_render_chart_review_handles_missing_chart() -> None:
    out = _render_chart_review_section({"missing": True, "patient_id": "pat-1"})
    assert "Patient chart not loaded" in out
    assert "pat-1" in out


def test_render_chart_review_renders_full_payload() -> None:
    chart = {
        "missing": False,
        "patient_id": "pat-1",
        "age": 36,
        "sex": "F",
        "anthropometrics": {"height": "67", "weight": "165"},
        "pmh": [
            {"display": "Type 2 diabetes mellitus", "code": "E11.9", "system": "ICD-10"},
        ],
        "allergies": [{"display": "Peanut", "narrative": "", "severity": "severe"}],
        "medications": [{"display": "Semaglutide 1mg/dose"}],
        "labs": [{
            "code": "4548-4", "label": "Hemoglobin A1c",
            "value": "6.8", "units": "%", "effective_date": "2026-04-10",
        }],
    }

    out = _render_chart_review_section(chart)

    assert "Type 2 diabetes mellitus" in out
    assert "Peanut" in out and "severe" in out
    assert "Semaglutide" in out
    assert "Hemoglobin A1c" in out and "6.8" in out
    assert 'value="67"' in out
    assert 'value="165"' in out


@patch("nutrition_charting.applications.nutrition_charting_app.build_chart_review")
@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_handle_renders_phase_d_pass2_sections(
    mock_note_cls: MagicMock, mock_build: MagicMock,
) -> None:
    """All Phase D pass-2 sections must appear in the modal HTML so the
    dietician can chart end-to-end in one open of the note."""
    import json as _json

    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note(
        id_="note-uuid-1", note_type_name="Nutrition"
    )
    mock_build.return_value = {"missing": True, "patient_id": "pat-1"}

    payload = NutritionChartingApp(event=_mock_event()).handle()[0].payload
    # The effect payload is a JSON-encoded LaunchModal effect — pull the raw
    # HTML out of `data.content` so substring checks aren't tripped up by
    # JSON's quote-escaping.
    html = _json.loads(payload)["data"]["content"]

    # Pass-2 multi-command sections render as collapsible blocks
    assert "section-goals" in html
    assert "section-educational_materials" in html
    assert "section-referrals" in html
    # Pass-2 single-command sections render too
    assert "section-counseling_narrative" in html
    assert "section-recommended_labs" in html
    assert "section-recommended_supplementation" in html
    assert "section-monitor_team_meeting" in html
    # Multi-row containers and the "+ Add" affordance are wired up
    assert 'data-multi-section="goals"' in html
    assert 'data-add-row="goals"' in html
    # Educational materials gets its canonical checklist
    assert 'data-multi-canonical="educational_materials"' in html
    assert "DASH diet" in html
    # Each section has a hidden-by-default "Refresh to see changes" link the
    # JS will un-hide after a save with delete > 0.
    assert 'id="refresh-link-goals"' in html
    assert 'data-refresh-link="goals"' in html
    assert "Refresh to see changes" in html


@patch("nutrition_charting.applications.nutrition_charting_app.build_chart_review")
@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_handle_renders_visit_type_aware_collapse_logic(
    mock_note_cls: MagicMock, mock_build: MagicMock,
) -> None:
    """The page JS must include the spec §4.1 follow-up collapse list and
    the radio-change handler that reapplies defaults."""
    import json as _json

    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note()
    mock_build.return_value = {"missing": True, "patient_id": "pat-1"}

    payload = NutritionChartingApp(event=_mock_event()).handle()[0].payload
    html = _json.loads(payload)["data"]["content"]

    # Per spec §4.1: Medical Chart Review + Social/Diet History + Dietary
    # Intake collapse on follow-up. The JS list must contain those three
    # exact section ids.
    assert "FOLLOW_UP_COLLAPSED_SECTIONS" in html
    assert "medical_chart_review" in html
    assert "social_diet_history" in html
    assert "dietary_intake" in html
    # Helpers + listeners are wired up.
    assert "function applyVisitTypeDefaults" in html
    assert "function collapseSection" in html
    assert "function setHeaderStatus" in html
    # The radio change handler reapplies defaults on toggle.
    assert 'input[name="visit_type"]' in html
    assert "applyVisitTypeDefaults(radio.value)" in html
    # Save success path collapses the section on a clean save and slides
    # the next section's header into the middle of the iframe so the
    # just-collapsed section stays visible right above it.
    assert "collapseSection(sectionId)" in html
    assert "scrollToNextSection(sectionId)" in html
    assert 'block: "center"' in html


@patch("nutrition_charting.applications.nutrition_charting_app.build_chart_review")
@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_handle_renders_section_header_status_styling(
    mock_note_cls: MagicMock, mock_build: MagicMock,
) -> None:
    """The header-row status mirror needs CSS for saved/error states so
    the dietician sees feedback after an auto-collapse."""
    import json as _json

    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note()
    mock_build.return_value = {"missing": True, "patient_id": "pat-1"}

    payload = NutritionChartingApp(event=_mock_event()).handle()[0].payload
    html = _json.loads(payload)["data"]["content"]

    assert ".nc-section-status--saved" in html
    assert ".nc-section-status--error" in html


def test_render_chart_review_escapes_html_in_user_data() -> None:
    chart = {
        "missing": False,
        "patient_id": "pat-1",
        "age": 36, "sex": "F",
        "anthropometrics": {"height": None, "weight": None},
        "pmh": [{"display": "<script>alert(1)</script>", "code": "X", "system": ""}],
        "allergies": [], "medications": [], "labs": [],
    }

    out = _render_chart_review_section(chart)

    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_render_page_escapes_script_close_in_pmh_for_js_context() -> None:
    """A Condition `display` containing `</script>` (plantable via FHIR /
    HL7 import) flows into `pmh_options[*].label` which gets serialized
    into the inline `<script>` block as part of `MULTI_SECTIONS`.
    `json.dumps` alone doesn't escape `<`, so the HTML tokenizer would
    see a literal `</script>` and terminate the script tag — letting the
    attacker's follow-on `<script>` execute. Verify the `<` is encoded
    as `\\u003c` instead, so the HTML parser never sees a script-close
    sequence while the JS engine still decodes the original text."""
    payload = "Hypertension</script><script>alert(1)</script>"
    chart = {
        "missing": False,
        "patient_id": "pat-1",
        "age": 36, "sex": "F",
        "anthropometrics": {"height": None, "weight": None},
        "pmh": [{"display": payload, "code": "I10", "system": "icd-10"}],
        "allergies": [], "medications": [], "labs": [],
    }

    html = _render_page(
        note_uuid="n-1",
        patient_id="pat-1",
        note_type_name="Nutrition Initial",
        chart=chart,
    )

    # The attacker's literal `</script><script>alert(1)` must not appear
    # anywhere in the rendered HTML — that's the byte sequence the HTML
    # tokenizer terminates the script element on.
    assert "</script><script>alert(1)" not in html
    # And the original `<` characters in the payload must have been
    # encoded — proves the escape was applied (not just the test data
    # being missing for some unrelated reason).
    assert "Hypertension\\u003c/script>\\u003cscript>alert(1)" in html


def test_render_page_emits_ghost_handling_for_inactive_indications() -> None:
    """The referrals row's `indications` multiselect renders options from
    current active PMH only, but the saved row stores a list of ICD-10
    codes. If a previously-selected condition is later retracted or
    resolved, the saved code has no DOM checkbox and the next save would
    silently strip the code from the committed Refer command (or delete
    the whole command if all indications drop). The render embeds JS
    that handles this case by drawing a checked "(no longer active)"
    ghost checkbox for any saved value not in the canonical option list,
    so `collectMultiSection` rolls the value back up on save.

    This is a smoke test that only verifies the ghost-handling code
    is present in the rendered JS — the actual checkbox is drawn at
    runtime after `loadFormState` returns the saved row values. End-
    to-end coverage requires a Canvas sandbox with a retracted
    Condition; this test guards against the fix being accidentally
    removed during refactors."""
    chart = {
        "missing": False,
        "patient_id": "pat-1",
        "age": 36, "sex": "F",
        "anthropometrics": {"height": None, "weight": None},
        "pmh": [{"display": "Hypertension", "code": "I10", "system": "icd-10"}],
        "allergies": [], "medications": [], "labs": [],
    }

    html = _render_page(
        note_uuid="n-1",
        patient_id="pat-1",
        note_type_name="Nutrition Initial",
        chart=chart,
    )

    # The ghost-checkbox annotation string must appear in the embedded
    # JS — proves the second-pass render for saved-but-not-in-msOpts
    # codes is wired in. Without it, retracted indications drop
    # silently on resave.
    assert "(no longer active)" in html
    # The CSS class hook for visually distinguishing ghost checkboxes
    # must also be present so a future stylesheet tweak can target them.
    assert "nc-checkbox--ghost" in html
    # And the `optsSet` membership map that determines what counts as
    # "ghost" must be built — guards against someone removing the set
    # tracking but leaving the ghost-render loop in place (which would
    # cause every saved code to render twice).
    assert "optsSet" in html
