"""Phase E tests: print payload assembly."""

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

from nutrition_charting.data import print_payload as pp


def _patient_mock(**fields: Any) -> MagicMock:
    p = MagicMock()
    p.first_name = fields.get("first_name", "Test")
    p.last_name = fields.get("last_name", "Patient")
    p.birth_date = fields.get("birth_date", date(1984, 5, 4))
    p.sex_at_birth = fields.get("sex_at_birth", "F")
    p.mrn = fields.get("mrn", "100200300")
    return p


def _note_mock(**fields: Any) -> MagicMock:
    n = MagicMock()
    n.datetime_of_service = fields.get("datetime_of_service", "2026-05-04 10:00")
    ntv = MagicMock()
    ntv.name = fields.get("note_type_name", "Nutrition Initial")
    n.note_type_version = ntv
    if fields.get("provider") is None:
        n.provider = None
    else:
        provider = MagicMock()
        provider.first_name = fields["provider"].get("first_name", "Test")
        provider.last_name = fields["provider"].get("last_name", "Provider")
        provider.npi_number = fields["provider"].get("npi_number", "1234567890")
        n.provider = provider
    return n


# ---- _age_in_years ----

def test_age_handles_birthday_already_passed_this_year() -> None:
    today = date.today()
    bd = date(today.year - 30, 1, 1)  # Jan 1 has passed for any non-Jan-1 today
    if (today.month, today.day) < (1, 1):  # impossible
        return
    assert pp._age_in_years(bd) == 30


def test_age_returns_one_less_when_birthday_not_yet_reached() -> None:
    today = date.today()
    # Birthday tomorrow — age should still be one less than year diff.
    if today == date(today.year, 12, 31):
        return  # skip on the one day this construction breaks
    bd = date(today.year - 25, today.month, min(today.day + 1, 28))
    if (today.month, today.day) < (bd.month, bd.day):
        assert pp._age_in_years(bd) == 24


def test_age_returns_none_for_missing_birth_date() -> None:
    assert pp._age_in_years(None) is None


# ---- _patient_block ----

@patch("nutrition_charting.data.print_payload.Patient")
def test_patient_block_assembles_full_record(mock_patient_cls: MagicMock) -> None:
    mock_patient_cls.objects.get.return_value = _patient_mock(
        first_name="Test", last_name="Patient", birth_date=date(1990, 1, 1),
        sex_at_birth="F",
    )

    out = pp._patient_block("pat-1")

    assert out["full_name"] == "Test Patient"
    assert out["sex_at_birth"] == "F"
    assert out["birth_date"] == "1990-01-01"
    assert isinstance(out["age"], int)
    assert out["mrn"] == "100200300"


@patch("nutrition_charting.data.print_payload.Patient")
def test_patient_block_returns_blanks_when_patient_missing(
    mock_patient_cls: MagicMock,
) -> None:
    class _DNE(Exception):
        pass

    mock_patient_cls.DoesNotExist = _DNE
    mock_patient_cls.objects.get.side_effect = _DNE()

    assert pp._patient_block("pat-missing") == {}


def test_patient_block_returns_empty_for_blank_id() -> None:
    assert pp._patient_block("") == {}


# ---- _note_block ----

@patch("nutrition_charting.data.print_payload.Note")
def test_note_block_includes_provider_and_note_type(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _note_mock(
        provider={"first_name": "Test", "last_name": "Provider", "npi_number": "1112223333"},
    )

    out = pp._note_block("note-1")

    assert out["provider_name"] == "Test Provider"
    assert out["provider_npi"] == "1112223333"
    assert out["note_type_name"] == "Nutrition Initial"


@patch("nutrition_charting.data.print_payload.Note")
def test_note_block_handles_missing_provider(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _note_mock(
        provider=None,
    )

    out = pp._note_block("note-1")

    assert out["provider_name"] == ""
    assert out["provider_npi"] == ""


def test_note_block_returns_empty_for_blank_uuid() -> None:
    assert pp._note_block("") == {}


# ---- _questionnaire_section / _flat_field / _multi_rows ----

def test_questionnaire_section_drops_empty_answers() -> None:
    sections = {"social_diet_history": {
        "appetite": "good", "chew_swallow": "", "nausea_vomiting": None,
        "diet_at_home": "Mediterranean",
    }}

    rows = pp._questionnaire_section("social_diet_history", sections)

    labels = [row["label"] for row in rows]
    assert "Appetite" in labels
    assert "Diet Followed at Home" in labels
    assert "Chew/Swallow" not in labels
    assert "Nausea/Vomiting" not in labels


def test_questionnaire_section_returns_empty_for_unknown_section() -> None:
    assert pp._questionnaire_section("nope", {}) == []


def test_flat_field_returns_safe_string() -> None:
    sections = {"counseling_narrative": {"counseling_narrative": "  Discussed portions  "}}
    assert pp._flat_field(sections, "counseling_narrative", "counseling_narrative") == \
        "Discussed portions"


def test_flat_field_returns_blank_for_unsaved_section() -> None:
    assert pp._flat_field({}, "counseling_narrative", "counseling_narrative") == ""


def test_multi_rows_flattens_and_drops_blanks() -> None:
    sections = {"goals": {"rows": [
        {"row_id": "goal:a", "goal_statement": "Walk daily"},
        {"row_id": "goal:b", "goal_statement": ""},
        {"row_id": "goal:c", "goal_statement": "  Drink water  "},
    ]}}

    out = pp._multi_rows(sections, "goals", "goal_statement")

    assert out == ["Walk daily", "Drink water"]


def test_multi_rows_returns_empty_when_section_missing() -> None:
    assert pp._multi_rows({}, "goals", "goal_statement") == []


# ---- _recommended_labs ----

def test_recommended_labs_resolves_canonical_keys_and_appends_other() -> None:
    sections = {"recommended_labs": {
        "selected": ["a1c", "vitamin_d"],
        "other": "TSH\nUric Acid",
    }}

    out = pp._recommended_labs(sections)

    assert "A1c / HbA1c" in out
    assert "Vitamin D 25-OH" in out
    assert "TSH" in out
    assert "Uric Acid" in out


def test_recommended_labs_passes_unknown_keys_through_unchanged() -> None:
    out = pp._recommended_labs({"recommended_labs": {"selected": ["new_panel"]}})
    assert out == ["new_panel"]


def test_recommended_labs_handles_other_as_list() -> None:
    out = pp._recommended_labs({"recommended_labs": {
        "selected": [], "other": ["TSH", " ", "Cortisol"],
    }})
    assert out == ["TSH", "Cortisol"]


def test_recommended_labs_returns_empty_when_section_missing() -> None:
    assert pp._recommended_labs({}) == []


# ---- _educational_materials ----

def test_educational_materials_uses_canonical_label_for_canonical_row_ids() -> None:
    sections = {"educational_materials": {"rows": [
        {"row_id": "material:dash_diet", "name": "DASH diet"},
        {"row_id": "material:low_fodmap", "name": "stale label"},
    ]}}

    out = pp._educational_materials(sections)

    assert "DASH diet" in out
    # The canonical-row-id path overrides whatever name was in the row
    # so a stale or renamed label can't ship in the print.
    assert "Low-FODMAP" in out
    assert "stale label" not in out


def test_educational_materials_passes_through_other_rows() -> None:
    sections = {"educational_materials": {"rows": [
        {"row_id": "material:abcd1234", "name": "Heart-healthy snacks"},
    ]}}

    out = pp._educational_materials(sections)

    assert out == ["Heart-healthy snacks"]


# ---- _monitor_team_meeting ----

def test_monitor_team_meeting_truthy_encodings() -> None:
    for truthy in (True, "true", "on", "1", 1, "yes"):
        out = pp._monitor_team_meeting({"monitor_team_meeting": {
            "monitor": truthy, "comment": "follow up",
        }})
        assert out["checked"] is True
        assert out["comment"] == "follow up"


def test_monitor_team_meeting_falsy_when_unchecked() -> None:
    out = pp._monitor_team_meeting({"monitor_team_meeting": {"monitor": False}})
    assert out == {"checked": False, "comment": ""}


# ---- build_print_payload integration ----

@patch("nutrition_charting.data.print_payload.build_chart_review")
@patch("nutrition_charting.data.print_payload.get_form_state")
@patch("nutrition_charting.data.print_payload.Note")
@patch("nutrition_charting.data.print_payload.Patient")
def test_build_print_payload_assembles_all_sections(
    mock_patient_cls: MagicMock, mock_note_cls: MagicMock,
    mock_form_state: MagicMock, mock_chart: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = _patient_mock()
    mock_note_cls.objects.select_related.return_value.get.return_value = _note_mock(
        provider={"first_name": "Test", "last_name": "Provider", "npi_number": "9"},
    )
    mock_chart.return_value = {
        "missing": False,
        "anthropometrics": {"height": "65", "weight": "150"},
        "pmh": [{"display": "Type 2 DM", "code": "E11.9"}],
        "allergies": [],
        "medications": [],
        "labs": [],
    }
    mock_form_state.return_value = {
        "visit_type": "follow_up",
        "sections": {
            "medical_chart_review": {"height": "67", "ubw": "155"},
            "social_diet_history": {"appetite": "good"},
            "estimated_nutrition_requirements": {"calories": "1800"},
            "counseling_narrative": {"counseling_narrative": "Discussed plate method"},
            "follow_up_appointment": {
                "follow_up_date": "2026-06-15",
                "follow_up_comment": "Recheck A1c",
            },
            "recommended_supplementation": {"supplementation": "Vitamin D 2000 IU"},
            "monitor_team_meeting": {"monitor": True, "comment": "BG control"},
            "goals": {"rows": [{"row_id": "goal:a", "goal_statement": "Walk daily"}]},
            "educational_materials": {"rows": [
                {"row_id": "material:dash_diet", "name": "DASH diet"},
            ]},
            "referrals": {"rows": [
                {"row_id": "ref:a", "notes_to_specialist": "Refer to GI"},
            ]},
            "recommended_labs": {"selected": ["a1c"], "other": "TSH"},
        },
    }

    payload = pp.build_print_payload("note-1", "pat-1")

    assert payload["visit_type"] == "follow_up"
    assert payload["patient"]["full_name"] == "Test Patient"
    assert payload["note"]["provider_name"] == "Test Provider"
    # Saved override beats chart fallback for height
    assert payload["anthropometrics"]["height"] == "67"
    assert payload["anthropometrics"]["weight"] == "150"  # from chart
    assert payload["anthropometrics"]["ubw"] == "155"
    assert payload["estimated_requirements"]["calories"] == "1800"
    assert payload["intervention"]["educational_materials"] == ["DASH diet"]
    assert payload["intervention"]["counseling_narrative"] == "Discussed plate method"
    assert payload["monitoring"]["goals"] == ["Walk daily"]
    assert payload["monitoring"]["follow_up_date"] == "2026-06-15"
    assert payload["coordination"]["referrals"] == ["Refer to GI"]
    assert "A1c / HbA1c" in payload["coordination"]["recommended_labs"]
    assert "TSH" in payload["coordination"]["recommended_labs"]
    assert payload["coordination"]["monitor_team_meeting"]["checked"] is True


def test_build_print_payload_tolerates_blank_ids() -> None:
    payload = pp.build_print_payload("", "")

    # Should never throw; returns empty/default shape so the template can
    # still render a placeholder document.
    assert payload["patient"] == {}
    assert payload["note"] == {}
    assert payload["visit_type"] == "initial"
    assert payload["chart"] == {"missing": True}
    assert payload["intervention"]["educational_materials"] == []
    assert payload["monitoring"]["goals"] == []
