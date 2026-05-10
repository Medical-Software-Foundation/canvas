"""Tests for the Phase D pass 2 multi-command section registry."""

from unittest.mock import MagicMock, patch

from canvas_sdk.commands import GoalCommand, InstructCommand, ReferCommand
from canvas_sdk.commands.commands.refer import ReferCommand as _ReferRef

from nutrition_charting.data.multi_command_sections import (
    DIET_EDUCATION_CODING,
    EDUCATIONAL_MATERIAL_OPTIONS,
    MULTI_COMMAND_SECTIONS,
    _build_educational_material_kwargs,
    _build_goal_kwargs,
    _build_referral_kwargs,
    _educational_material_row_ready,
    _goal_row_ready,
    _referral_row_ready,
    get_section,
)


def test_registry_includes_pass2_sections() -> None:
    assert set(MULTI_COMMAND_SECTIONS) == {"goals", "educational_materials", "referrals"}


def test_get_section_returns_none_for_unknown() -> None:
    assert get_section("nope") is None


def test_goals_section_uses_goal_command() -> None:
    section = get_section("goals")
    assert section is not None
    assert section["command_class"] is GoalCommand
    assert any(field[0] == "goal_statement" for field in section["row_fields"])


def test_educational_materials_section_uses_instruct_command() -> None:
    section = get_section("educational_materials")
    assert section is not None
    assert section["command_class"] is InstructCommand
    # Canonical options are exposed for the front-end checklist.
    assert section["checklist_options"] == EDUCATIONAL_MATERIAL_OPTIONS
    assert section["checklist_field"] == "name"


def test_referrals_section_uses_refer_command() -> None:
    section = get_section("referrals")
    assert section is not None
    assert section["command_class"] is ReferCommand


# ---- Goals builder ----

def test_goal_builder_returns_goal_statement_kwargs() -> None:
    assert _build_goal_kwargs({"goal_statement": "Drink 64oz water/day"}) == {
        "goal_statement": "Drink 64oz water/day",
    }


def test_goal_builder_strips_whitespace() -> None:
    assert _build_goal_kwargs({"goal_statement": "  walk daily  "}) == {
        "goal_statement": "walk daily",
    }


def test_goal_builder_returns_empty_for_blank_text() -> None:
    assert _build_goal_kwargs({"goal_statement": ""}) == {}
    assert _build_goal_kwargs({"goal_statement": "   "}) == {}
    assert _build_goal_kwargs({}) == {}


def test_goal_row_ready_requires_text() -> None:
    assert _goal_row_ready({"goal_statement": "x"})
    assert not _goal_row_ready({"goal_statement": ""})
    assert not _goal_row_ready({})


# ---- Educational materials builder ----

def test_educational_material_builder_emits_diet_education_coding_and_comment() -> None:
    """The Canvas Instruct UI renders `coding.display` as the header
    ("Instruct: Diet education") and `comment` as the body ("Low-FODMAP")."""
    kwargs = _build_educational_material_kwargs({"name": "Low-FODMAP"})
    assert kwargs["comment"] == "Low-FODMAP"
    assert kwargs["coding"] == DIET_EDUCATION_CODING
    assert kwargs["coding"]["display"] == "Diet education"


def test_educational_material_builder_does_not_share_coding_dict_between_calls() -> None:
    """Each row gets its own coding dict so a downstream mutation on one
    Instruct command can't leak into another."""
    a = _build_educational_material_kwargs({"name": "DASH diet"})
    b = _build_educational_material_kwargs({"name": "Mediterranean diet"})
    assert a["coding"] is not b["coding"]


def test_educational_material_builder_returns_empty_when_blank() -> None:
    assert _build_educational_material_kwargs({"name": ""}) == {}
    assert _build_educational_material_kwargs({}) == {}


def test_educational_material_row_ready_tracks_name() -> None:
    assert _educational_material_row_ready({"name": "DASH"})
    assert not _educational_material_row_ready({"name": ""})


# ---- Referrals builder ----

def test_referral_builder_uses_notes_to_specialist() -> None:
    assert _build_referral_kwargs(
        {"notes_to_specialist": "Refer to GI for further workup"},
    ) == {"notes_to_specialist": "Refer to GI for further workup"}


def test_referral_builder_returns_empty_for_blank() -> None:
    assert _build_referral_kwargs({"notes_to_specialist": ""}) == {}
    assert _build_referral_kwargs({}) == {}


def test_referral_row_ready_requires_all_three_required_fields() -> None:
    """Notes-to-specialist + clinical_question + at least one indication
    are all required (asterisked in the form). Missing any one drops the
    row from emit so the Commands tab doesn't accumulate half-formed
    Refer commands."""
    full_row = {
        "notes_to_specialist": "Refer for cardiology eval",
        "clinical_question": "Specialized intervention",
        "indications": ["I10"],
    }
    assert _referral_row_ready(full_row)


def test_referral_row_ready_rejects_missing_notes_to_specialist() -> None:
    assert not _referral_row_ready({
        "notes_to_specialist": "",
        "clinical_question": "Specialized intervention",
        "indications": ["I10"],
    })


def test_referral_row_ready_rejects_missing_clinical_question() -> None:
    assert not _referral_row_ready({
        "notes_to_specialist": "Refer",
        "clinical_question": "",
        "indications": ["I10"],
    })


def test_referral_row_ready_rejects_missing_indications() -> None:
    """An empty indications list (patient has no PMH on the chart, or the
    dietician simply didn't pick any) drops the row."""
    assert not _referral_row_ready({
        "notes_to_specialist": "Refer",
        "clinical_question": "Specialized intervention",
        "indications": [],
    })


def test_referral_builder_includes_clinical_question_when_set() -> None:
    """The form posts the enum's `.value` (e.g. "Specialized intervention");
    the builder resolves it back to the ClinicalQuestion enum member that
    pydantic accepts on ReferCommand."""
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "clinical_question": "Specialized intervention",
    })
    assert kwargs["clinical_question"] is _ReferRef.ClinicalQuestion.SPECIALIZED_INTERVENTION


def test_referral_builder_includes_priority_when_set() -> None:
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "priority": "Urgent",
    })
    assert kwargs["priority"] is _ReferRef.Priority.URGENT


def test_referral_builder_drops_unrecognized_enum_values() -> None:
    """Defensive: a stale or hand-edited form value shouldn't blow up the
    save — silently drop the unknown value so the row still emits."""
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "clinical_question": "totally bogus",
        "priority": "",
    })
    assert "clinical_question" not in kwargs
    assert "priority" not in kwargs


def test_referral_builder_includes_internal_comment_and_visit_note() -> None:
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "comment": "  patient prefers in-network ",
        "include_visit_note": True,
    })
    assert kwargs["comment"] == "patient prefers in-network"
    assert kwargs["include_visit_note"] is True


def test_referral_builder_treats_form_truthy_strings_as_visit_note_on() -> None:
    """The HTML checkbox posts boolean True from JS now, but accept the
    legacy 'on' / 'true' encodings for back-compat with stored form-state."""
    for truthy in (True, "true", "on", "1", 1, "yes"):
        kwargs = _build_referral_kwargs({
            "notes_to_specialist": "Refer to GI",
            "include_visit_note": truthy,
        })
        assert kwargs["include_visit_note"] is True


def test_referral_builder_omits_visit_note_when_unchecked() -> None:
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "include_visit_note": False,
    })
    assert "include_visit_note" not in kwargs


def test_referral_builder_emits_service_provider_when_all_four_fields_present() -> None:
    """ServiceProvider's first_name/last_name/specialty/practice_name are
    all required strings on the Canvas SDK model, so the builder only
    constructs a provider when all four are filled."""
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "provider_first_name": "Test",
        "provider_last_name": "Specialist",
        "provider_specialty": "Gastroenterology",
        "provider_practice_name": "Sample Specialty Practice",
    })
    sp = kwargs.get("service_provider")
    assert sp is not None
    assert sp.first_name == "Test"
    assert sp.last_name == "Specialist"
    assert sp.specialty == "Gastroenterology"
    assert sp.practice_name == "Sample Specialty Practice"


def test_referral_builder_omits_service_provider_when_partial() -> None:
    """A partially-filled provider (e.g. just first name) wouldn't pass
    pydantic validation on ServiceProvider — drop it entirely so the
    referral still emits with the rest of the fields."""
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "provider_first_name": "Test",
        # other three missing
    })
    assert "service_provider" not in kwargs


# ---- Phase 4.5: typeahead-resolved provider preference --------------------

@patch("nutrition_charting.data.multi_command_sections.ServiceProviderRecord")
def test_referral_builder_prefers_resolved_provider_over_manual_fields(
    mock_record_cls: MagicMock,
) -> None:
    """When `service_provider_id` is set, the builder reads canonical
    name/specialty/practice from the DB record and ignores any manual
    fields the user might have left in the row."""
    record = MagicMock()
    record.first_name = "Sarah"
    record.last_name = "Cohen"
    record.specialty = "Cardiology"
    record.practice_name = "Heart Center"
    mock_record_cls.objects.get.return_value = record

    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Cardiology eval",
        "service_provider_id": "sp-uuid-1",
        # Stale manual fields that should be ignored:
        "provider_first_name": "Old",
        "provider_last_name": "Manual",
        "provider_specialty": "Stale",
        "provider_practice_name": "Stale Practice",
    })

    sp = kwargs.get("service_provider")
    assert sp is not None
    assert sp.first_name == "Sarah"
    assert sp.last_name == "Cohen"
    assert sp.specialty == "Cardiology"
    assert sp.practice_name == "Heart Center"
    mock_record_cls.objects.get.assert_called_once_with(id="sp-uuid-1")


@patch("nutrition_charting.data.multi_command_sections.ServiceProviderRecord")
def test_referral_builder_falls_back_to_manual_when_resolved_record_missing(
    mock_record_cls: MagicMock,
) -> None:
    """A stale `service_provider_id` (record was deleted between save and
    re-save) shouldn't drop the referral — fall back to whatever manual
    fields the row has."""
    class _DNE(Exception):
        pass

    mock_record_cls.DoesNotExist = _DNE
    mock_record_cls.objects.get.side_effect = _DNE()

    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Cardiology eval",
        "service_provider_id": "sp-uuid-deleted",
        "provider_first_name": "Test",
        "provider_last_name": "Specialist",
        "provider_specialty": "Cardiology",
        "provider_practice_name": "Sample Practice",
    })

    sp = kwargs.get("service_provider")
    assert sp is not None
    assert sp.first_name == "Test"
    assert sp.last_name == "Specialist"


@patch("nutrition_charting.data.multi_command_sections.ServiceProviderRecord")
def test_referral_builder_falls_back_when_resolved_record_missing_required_field(
    mock_record_cls: MagicMock,
) -> None:
    """DB records can be incomplete (e.g. an organization with a blank
    last_name). The pydantic ServiceProvider value object requires all
    four — when the record can't satisfy that, fall back to the manual
    fields rather than dropping the provider entirely."""
    record = MagicMock()
    record.first_name = "Heart Center"
    record.last_name = ""  # organization, no last name
    record.specialty = "Cardiology"
    record.practice_name = "Heart Center"
    mock_record_cls.objects.get.return_value = record

    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Cardiology eval",
        "service_provider_id": "sp-uuid-org",
        "provider_first_name": "Sarah",
        "provider_last_name": "Cohen",
        "provider_specialty": "Cardiology",
        "provider_practice_name": "Heart Center",
    })

    sp = kwargs.get("service_provider")
    assert sp is not None
    assert sp.first_name == "Sarah"
    assert sp.last_name == "Cohen"


def test_referral_builder_parses_indications_from_textarea() -> None:
    """The form posts indications as a newline-separated textarea; builder
    splits to list[str] for ReferCommand.diagnosis_codes."""
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "indications": "  E11.9\n\nF33.1  \nM25.561",
    })
    assert kwargs["diagnosis_codes"] == ["E11.9", "F33.1", "M25.561"]


def test_referral_builder_accepts_indications_as_list() -> None:
    """When form-state round-trips a previously-saved row the indications
    may already be a list; tolerate that shape too."""
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "indications": ["E11.9", "  ", "F33.1"],
    })
    assert kwargs["diagnosis_codes"] == ["E11.9", "F33.1"]


def test_referral_builder_omits_indications_when_blank() -> None:
    kwargs = _build_referral_kwargs({
        "notes_to_specialist": "Refer to GI",
        "indications": "  \n\n",
    })
    assert "diagnosis_codes" not in kwargs


def test_referrals_section_row_fields_include_provider_and_indications_fields() -> None:
    section = MULTI_COMMAND_SECTIONS["referrals"]
    field_ids = [f[0] for f in section["row_fields"]]
    for fid in (
        "provider_first_name", "provider_last_name", "provider_specialty",
        "provider_practice_name", "indications",
    ):
        assert fid in field_ids, fid


def test_referrals_section_row_fields_include_enum_dropdowns() -> None:
    """The registry must expose select options for the front-end to render
    Clinical Question / Priority dropdowns. Each enum dropdown starts with
    a "—" sentinel so the dietician can leave it unset."""
    section = MULTI_COMMAND_SECTIONS["referrals"]
    fields_by_id = {f[0]: f for f in section["row_fields"]}

    cq = fields_by_id["clinical_question"]
    assert cq[2] == "select"
    cq_values = [v for v, _ in cq[3]]
    assert "" in cq_values  # sentinel for "not set"
    assert "Specialized intervention" in cq_values
    assert "Cognitive Assistance (Advice/Guidance)" in cq_values

    pr = fields_by_id["priority"]
    assert pr[2] == "select"
    pr_values = [v for v, _ in pr[3]]
    assert "Routine" in pr_values
    assert "Urgent" in pr_values

    assert fields_by_id["include_visit_note"][2] == "checkbox"
