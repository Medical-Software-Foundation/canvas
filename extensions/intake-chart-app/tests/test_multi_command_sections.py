"""Tests for the multi-command section reconciler + concrete sections."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from intake_chart_app.data.multi_command_sections import (
    AllergiesSection,
    MedicationsSection,
    MultiCommandSection,
    ProblemsSection,
    RowOutcome,
)


# ---------------------------------------------------------------------------
# Reconciler base behaviour, exercised via a fake subclass.
# ---------------------------------------------------------------------------


class _FakeSection(MultiCommandSection):
    section_id = "fake"

    def _add(self, note_uuid, row_id, values, prior_uuid):
        return RowOutcome(
            effects=[f"originate:{row_id}"],
            map_uuid=prior_uuid or f"new-uuid:{row_id}",
        )

    def _edit(self, note_uuid, row_id, values, prior_uuid):
        return RowOutcome(
            effects=[f"edit:{row_id}"],
            map_uuid=prior_uuid or f"edit-uuid:{row_id}",
        )

    def _remove(self, note_uuid, row_id, values, prior_uuid):
        return RowOutcome(
            effects=[f"remove:{row_id}"],
            map_uuid=prior_uuid or f"remove-uuid:{row_id}",
        )


def test_confirm_emits_no_effects_and_preserves_prior_map():
    section = _FakeSection()
    effects, new_map = section.reconcile(
        "note-1",
        {"row-A": {"action": "confirm"}},
        {"row-A": "cmd-A"},
    )
    assert effects == []
    assert new_map == {"row-A": "cmd-A"}


def test_confirm_with_no_prior_uuid_yields_empty_map_entry():
    section = _FakeSection()
    effects, new_map = section.reconcile(
        "note-1", {"row-A": {"action": "confirm"}}, {},
    )
    assert effects == []
    assert new_map == {}  # nothing to preserve


def test_add_emits_originate_and_records_uuid():
    section = _FakeSection()
    effects, new_map = section.reconcile(
        "note-1", {"new:1": {"action": "add", "values": {}}}, {},
    )
    assert effects == ["originate:new:1"]
    assert new_map == {"new:1": "new-uuid:new:1"}


def test_remove_emits_remove_effect_and_records_command_uuid():
    section = _FakeSection()
    effects, new_map = section.reconcile(
        "note-1", {"row-A": {"action": "remove"}}, {},
    )
    assert effects == ["remove:row-A"]
    assert new_map == {"row-A": "remove-uuid:row-A"}


def test_edit_with_existing_uuid_reuses_it():
    section = _FakeSection()
    effects, new_map = section.reconcile(
        "note-1",
        {"row-A": {"action": "edit", "values": {}}},
        {"row-A": "cmd-A"},
    )
    assert effects == ["edit:row-A"]
    assert new_map == {"row-A": "cmd-A"}


def test_unknown_action_treated_as_confirm():
    section = _FakeSection()
    effects, new_map = section.reconcile(
        "note-1",
        {"row-A": {"action": "wat"}},
        {"row-A": "cmd-A"},
    )
    assert effects == []
    assert new_map == {"row-A": "cmd-A"}


def test_blank_row_id_skipped():
    section = _FakeSection()
    effects, new_map = section.reconcile(
        "note-1", {"": {"action": "add"}}, {},
    )
    assert effects == []
    assert new_map == {}


# ---------------------------------------------------------------------------
# ProblemsSection (Diagnose / UpdateDiagnosis / ResolveCondition)
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.multi_command_sections.DiagnoseCommand")
def test_problems_add_emits_diagnose_with_icd10(MockDx, note_uuid):
    section = ProblemsSection()
    instance = MockDx.return_value
    instance.originate.return_value = MagicMock(name="diag-effect")
    effects, new_map = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {"icd10_code": "E11.9", "background": "newly diagnosed"}}},
        {},
    )
    assert MockDx.call_args.kwargs["icd10_code"] == "E11.9"
    assert MockDx.call_args.kwargs["background"] == "newly diagnosed"
    assert MockDx.call_args.kwargs["note_uuid"] == note_uuid
    instance.originate.assert_called_once()
    assert "new:1" in new_map


@patch("intake_chart_app.data.multi_command_sections.DiagnoseCommand")
def test_problems_add_drops_row_with_no_icd10(MockDx, note_uuid):
    section = ProblemsSection()
    effects, new_map = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {"background": "incomplete"}}},
        {},
    )
    assert effects == []
    assert new_map == {}
    MockDx.assert_not_called()


def test_problems_edit_is_no_op_after_ui_drop(note_uuid):
    """Edit affordance dropped from Problems UI — UpdateDiagnosisCommand was
    unreliable on the target Canvas instance, so Resolve + Add new is the
    supported workflow. _edit short-circuits defensively so a stale draft
    with action="edit" can't silently emit a half command."""
    section = ProblemsSection()
    effects, new_map = section.reconcile(
        note_uuid,
        {"condition:abc-123": {
            "action": "edit",
            "values": {"condition_code": "I10", "new_condition_code": "I10"},
        }},
        {},
    )
    assert effects == []
    assert new_map == {}


@patch("intake_chart_app.data.multi_command_sections.ResolveConditionCommand")
def test_problems_remove_emits_resolve_with_condition_id(MockResolve, note_uuid):
    section = ProblemsSection()
    instance = MockResolve.return_value
    effects, new_map = section.reconcile(
        note_uuid,
        {"condition:abc-123": {"action": "remove", "values": {"rationale": "no longer active"}}},
        {},
    )
    kwargs = MockResolve.call_args.kwargs
    # row_id strips the "condition:" prefix to get the actual chart row UUID.
    assert kwargs["condition_id"] == "abc-123"
    assert kwargs["rationale"] == "no longer active"
    instance.originate.assert_called_once()


@patch("intake_chart_app.data.multi_command_sections.ResolveConditionCommand")
def test_problems_remove_uses_default_rationale_when_blank(MockResolve, note_uuid):
    section = ProblemsSection()
    section.reconcile(
        note_uuid,
        {"condition:abc": {"action": "remove", "values": {}}},
        {},
    )
    rationale = MockResolve.call_args.kwargs["rationale"]
    assert "intake" in rationale.lower()


# ---------------------------------------------------------------------------
# AllergiesSection (Allergy / RemoveAllergy with edit-as-replace)
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.multi_command_sections.AllergyCommand")
def test_allergies_add_emits_allergy(MockAllergy, note_uuid):
    """Add: parses the ``"<concept_id>|<concept_type>"`` compound code that
    the /intake/search/allergy proxy emits, builds an ``Allergen`` TypedDict
    matching the SDK's expected shape, and emits one originate effect."""
    from canvas_sdk.commands.commands.allergy import AllergenType

    section = AllergiesSection()
    instance = MockAllergy.return_value
    effects, new_map = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {
            "allergen_code": "12345|2",
            "severity": "severe",
            "narrative": "anaphylaxis",
        }}},
        {},
    )
    kwargs = MockAllergy.call_args.kwargs
    assert kwargs["allergy"] == {
        "concept_id": 12345,
        "concept_type": AllergenType.MEDICATION,
    }
    assert kwargs["narrative"] == "anaphylaxis"
    # Severity passes through the AllergyCommand.Severity enum constructor,
    # which is mocked here — just assert it was set.
    assert "severity" in kwargs
    instance.originate.assert_called_once()


@patch("intake_chart_app.data.multi_command_sections.AllergyCommand")
@patch("intake_chart_app.data.multi_command_sections.RemoveAllergyCommand")
def test_allergies_edit_is_no_op_after_ui_drop(MockRemove, MockAllergy, note_uuid):
    """Edit affordance was dropped from the Allergies UI in UAT (it was a
    remove+recreate workaround that produced no commands when the search
    widget's value wasn't captured). _edit short-circuits defensively in
    case a stale draft rides through with action="edit"."""
    section = AllergiesSection()
    effects, new_map = section.reconcile(
        note_uuid,
        {"allergy:abc-123": {"action": "edit", "values": {
            "allergen_code": "67890|1", "severity": "mild",
        }}},
        {},
    )
    assert effects == []
    assert new_map == {}
    MockRemove.assert_not_called()
    MockAllergy.assert_not_called()


@patch("intake_chart_app.data.multi_command_sections.RemoveAllergyCommand")
def test_allergies_remove_emits_remove_allergy_with_id(MockRemove, note_uuid):
    section = AllergiesSection()
    instance = MockRemove.return_value
    effects, new_map = section.reconcile(
        note_uuid,
        {"allergy:abc-123": {"action": "remove", "values": {}}},
        {},
    )
    assert MockRemove.call_args.kwargs["allergy_id"] == "abc-123"
    assert "intake" in MockRemove.call_args.kwargs["narrative"].lower()
    instance.originate.assert_called_once()


# ---------------------------------------------------------------------------
# MedicationsSection (MedicationStatement / StopMedication)
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.multi_command_sections.MedicationStatementCommand")
def test_medications_add_emits_medication_statement(MockMS, note_uuid):
    section = MedicationsSection()
    instance = MockMS.return_value
    section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {
            "fdb_code": "12345", "sig": "1 tablet daily",
        }}},
        {},
    )
    kwargs = MockMS.call_args.kwargs
    assert kwargs["fdb_code"] == "12345"
    assert kwargs["sig"] == "1 tablet daily"
    instance.originate.assert_called_once()


@patch("intake_chart_app.data.multi_command_sections.MedicationStatementCommand")
@patch("intake_chart_app.data.multi_command_sections.StopMedicationCommand")
def test_medications_edit_is_no_op_after_ui_drop(MockStop, MockMS, note_uuid):
    """Edit affordance dropped from Medications UI — was a stop+recreate
    workaround that emitted only StopMedicationCommand because the search
    widget's value wasn't captured in the edit panel (read as a buggy
    'edit triggers stop' in UAT). Defensive no-op to absorb stale drafts."""
    section = MedicationsSection()
    effects, new_map = section.reconcile(
        note_uuid,
        {"medication:m-1": {"action": "edit", "values": {
            "fdb_code": "12345", "sig": "2 tablets daily",
        }}},
        {},
    )
    assert effects == []
    assert new_map == {}
    MockStop.assert_not_called()
    MockMS.assert_not_called()


@patch("intake_chart_app.data.multi_command_sections.StopMedicationCommand")
def test_medications_remove_emits_stop_with_id(MockStop, note_uuid):
    section = MedicationsSection()
    instance = MockStop.return_value
    section.reconcile(
        note_uuid,
        {"medication:m-1": {"action": "remove", "values": {"rationale": "discontinued"}}},
        {},
    )
    assert MockStop.call_args.kwargs["medication_id"] == "m-1"
    assert MockStop.call_args.kwargs["rationale"] == "discontinued"
    instance.originate.assert_called_once()


# ---------------------------------------------------------------------------
# History-section helpers (_icd10_freetext, _snomed_payload, _parse_date)
# ---------------------------------------------------------------------------


def test_icd10_freetext_returns_display_name_when_present():
    """The history sections submit the picked ICD-10 entry's display
    name as plain free text (no parenthesised code) — Canvas's chart
    renderer trips on the ``"<display> (<code>)"`` shape and shows the
    row with a blank value. The shape that renders correctly is
    ``past_medical_history=<display name>`` (or the ICD-10 code as a
    fallback)."""
    from intake_chart_app.data.multi_command_sections import _icd10_freetext

    assert _icd10_freetext(
        {"medical_history_code": "E11.9",
         "medical_history_code__display": "Type 2 diabetes mellitus, without complications"},
        "medical_history_code",
    ) == "Type 2 diabetes mellitus, without complications"


def test_icd10_freetext_with_empty_code_returns_none():
    from intake_chart_app.data.multi_command_sections import _icd10_freetext

    assert _icd10_freetext({"medical_history_code": ""}, "medical_history_code") is None
    assert _icd10_freetext({}, "medical_history_code") is None


def test_icd10_freetext_falls_back_to_code_when_display_missing():
    """Defensive: if the picker loses the display name, submit the bare code
    rather than nothing."""
    from intake_chart_app.data.multi_command_sections import _icd10_freetext

    assert _icd10_freetext({"medical_history_code": "E11.9"}, "medical_history_code") == "E11.9"


# _snomed_payload is currently unused but stays available for any future
# SDK command that requires SNOMED Coding dicts. Anchor it lives so
# re-introducing a SNOMED
# section doesn't have to rebuild the helper.
def test_snomed_payload_still_builds_coding_dict():
    from intake_chart_app.data.multi_command_sections import _snomed_payload, SNOMED_SYSTEM

    assert _snomed_payload(
        {"x_code": "44054006", "x_code__display": "Type 2 diabetes mellitus"},
        "x_code",
    ) == {
        "system": SNOMED_SYSTEM,
        "code": "44054006",
        "display": "Type 2 diabetes mellitus",
    }


def test_parse_date_iso_string():
    from datetime import date
    from intake_chart_app.data.multi_command_sections import _parse_date

    assert _parse_date("2020-03-15") == date(2020, 3, 15)


def test_parse_date_empty_or_garbage_returns_none():
    from intake_chart_app.data.multi_command_sections import _parse_date

    assert _parse_date("") is None
    assert _parse_date(None) is None
    assert _parse_date("not-a-date") is None
    assert _parse_date("2020-13-01") is None  # invalid month


# ---------------------------------------------------------------------------
# MedicalHistorySection
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.multi_command_sections.MedicalHistoryCommand")
def test_medical_history_add_emits_command_with_icd10_freetext(MockCmd, note_uuid):
    from intake_chart_app.data.multi_command_sections import MedicalHistorySection

    section = MedicalHistorySection()
    inst = MockCmd.return_value
    effects, new_map = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {
            "medical_history_code": "E11.9",
            "medical_history_code__display": "Type 2 diabetes mellitus, without complications",
            "approximate_start_date": "2010-06-01",
            "approximate_end_date": "",
            "comments": "Diet-controlled",
        }}},
        {},
    )
    kwargs = MockCmd.call_args.kwargs
    assert kwargs["past_medical_history"] == "Type 2 diabetes mellitus, without complications"
    from datetime import date
    assert kwargs["approximate_start_date"] == date(2010, 6, 1)
    assert "approximate_end_date" not in kwargs  # empty input → field omitted
    assert kwargs["comments"] == "Diet-controlled"
    inst.originate.assert_called_once()
    assert len(effects) == 1


@patch("intake_chart_app.data.multi_command_sections.MedicalHistoryCommand")
def test_medical_history_add_empty_code_short_circuits(MockCmd, note_uuid):
    """No picked ICD-10 code → no command emitted, no map entry."""
    from intake_chart_app.data.multi_command_sections import MedicalHistorySection

    section = MedicalHistorySection()
    effects, new_map = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {"medical_history_code": ""}}},
        {},
    )
    assert effects == []
    assert new_map == {}
    MockCmd.assert_not_called()


def test_medical_history_edit_raises(note_uuid):
    from intake_chart_app.data.multi_command_sections import MedicalHistorySection

    section = MedicalHistorySection()
    with pytest.raises(NotImplementedError):
        section._edit(note_uuid, "medical_history:abc", {}, None)


def test_medical_history_remove_raises(note_uuid):
    from intake_chart_app.data.multi_command_sections import MedicalHistorySection

    section = MedicalHistorySection()
    with pytest.raises(NotImplementedError):
        section._remove(note_uuid, "medical_history:abc", {}, None)


# ---------------------------------------------------------------------------
# SurgicalHistorySection
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.multi_command_sections.PastSurgicalHistoryCommand")
def test_surgical_history_add_emits_command_with_unstructured_coding(MockCmd, note_uuid):
    """``past_surgical_history`` is typed ``str | Coding`` — Canvas's chart
    renderer treats it as a structured coding, so plain strings render
    blank. ICD-10 picks ride through as ``{"system": "UNSTRUCTURED",
    "code": ..., "display": ...}`` which the validator accepts."""
    from intake_chart_app.data.multi_command_sections import SurgicalHistorySection, UNSTRUCTURED_SYSTEM

    section = SurgicalHistorySection()
    inst = MockCmd.return_value
    effects, new_map = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {
            "surgical_history_code": "Z98.890",
            "surgical_history_code__display": "Other specified postprocedural states",
            "approximate_date": "2001-08-14",
            "comment": "Laparoscopic appendectomy",
        }}},
        {},
    )
    kwargs = MockCmd.call_args.kwargs
    assert kwargs["past_surgical_history"] == {
        "system": UNSTRUCTURED_SYSTEM,
        "code": "Z98.890",
        "display": "Other specified postprocedural states",
    }
    from datetime import date
    assert kwargs["approximate_date"] == date(2001, 8, 14)
    assert kwargs["comment"] == "Laparoscopic appendectomy"
    inst.originate.assert_called_once()


@patch("intake_chart_app.data.multi_command_sections.PastSurgicalHistoryCommand")
def test_surgical_history_add_empty_code_short_circuits(MockCmd, note_uuid):
    from intake_chart_app.data.multi_command_sections import SurgicalHistorySection

    section = SurgicalHistorySection()
    effects, _ = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {"surgical_history_code": ""}}},
        {},
    )
    assert effects == []
    MockCmd.assert_not_called()


def test_surgical_history_edit_raises(note_uuid):
    from intake_chart_app.data.multi_command_sections import SurgicalHistorySection

    section = SurgicalHistorySection()
    with pytest.raises(NotImplementedError):
        section._edit(note_uuid, "surgical_history:abc", {}, None)


def test_surgical_history_remove_raises(note_uuid):
    from intake_chart_app.data.multi_command_sections import SurgicalHistorySection

    section = SurgicalHistorySection()
    with pytest.raises(NotImplementedError):
        section._remove(note_uuid, "surgical_history:abc", {}, None)


# ---------------------------------------------------------------------------
# FamilyHistorySection
# ---------------------------------------------------------------------------


@patch("intake_chart_app.data.multi_command_sections.FamilyHistoryCommand")
def test_family_history_add_with_relative_and_icd10_emits_unstructured_coding(
    MockCmd, note_uuid,
):
    """``family_history`` is typed ``str | Coding`` — Canvas's chart renderer
    needs the structured Coding shape, so ICD-10 picks ride through as
    ``{"system": "UNSTRUCTURED", "code": ..., "display": ...}``."""
    from intake_chart_app.data.multi_command_sections import FamilyHistorySection, UNSTRUCTURED_SYSTEM

    section = FamilyHistorySection()
    inst = MockCmd.return_value
    effects, new_map = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {
            "relative": "Mother",
            "family_history_code": "M06.9",
            "family_history_code__display": "Rheumatoid arthritis, unspecified",
            "note": "diagnosed in her 40s",
        }}},
        {},
    )
    kwargs = MockCmd.call_args.kwargs
    assert kwargs["relative"] == "Mother"
    assert kwargs["family_history"] == {
        "system": UNSTRUCTURED_SYSTEM,
        "code": "M06.9",
        "display": "Rheumatoid arthritis, unspecified",
    }
    assert kwargs["note"] == "diagnosed in her 40s"
    inst.originate.assert_called_once()


@patch("intake_chart_app.data.multi_command_sections.FamilyHistoryCommand")
def test_family_history_add_relative_only_emits_without_condition(MockCmd, note_uuid):
    """Just relative, no condition pick — the chart-sidebar 'None reported'
    pattern. The command originates with no ``family_history`` kwarg."""
    from intake_chart_app.data.multi_command_sections import FamilyHistorySection

    section = FamilyHistorySection()
    effects, _ = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {"relative": "Father"}}},
        {},
    )
    kwargs = MockCmd.call_args.kwargs
    assert kwargs["relative"] == "Father"
    assert "family_history" not in kwargs
    assert "note" not in kwargs
    assert len(effects) == 1


@patch("intake_chart_app.data.multi_command_sections.FamilyHistoryCommand")
def test_family_history_add_empty_relative_short_circuits(MockCmd, note_uuid):
    """Without a relative the row is meaningless — short-circuit even if
    a condition was picked."""
    from intake_chart_app.data.multi_command_sections import FamilyHistorySection

    section = FamilyHistorySection()
    effects, _ = section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {
            "relative": "",
            "family_history_code": "M06.9",
            "family_history_code__display": "Rheumatoid arthritis, unspecified",
        }}},
        {},
    )
    assert effects == []
    MockCmd.assert_not_called()


@patch("intake_chart_app.data.multi_command_sections.FamilyHistoryCommand")
def test_family_history_add_icd10_display_missing_falls_back_to_code_in_coding(
    MockCmd, note_uuid,
):
    """Defensive: if the picker lands a code without a display name, the
    Coding's display falls back to the code rather than being empty."""
    from intake_chart_app.data.multi_command_sections import FamilyHistorySection, UNSTRUCTURED_SYSTEM

    section = FamilyHistorySection()
    section.reconcile(
        note_uuid,
        {"new:1": {"action": "add", "values": {
            "relative": "Father", "family_history_code": "E11.9",
        }}},
        {},
    )
    assert MockCmd.call_args.kwargs["family_history"] == {
        "system": UNSTRUCTURED_SYSTEM,
        "code": "E11.9",
        "display": "E11.9",
    }


def test_family_history_edit_raises(note_uuid):
    from intake_chart_app.data.multi_command_sections import FamilyHistorySection

    section = FamilyHistorySection()
    with pytest.raises(NotImplementedError):
        section._edit(note_uuid, "family_history:abc", {}, None)


def test_family_history_remove_raises(note_uuid):
    from intake_chart_app.data.multi_command_sections import FamilyHistorySection

    section = FamilyHistorySection()
    with pytest.raises(NotImplementedError):
        section._remove(note_uuid, "family_history:abc", {}, None)
