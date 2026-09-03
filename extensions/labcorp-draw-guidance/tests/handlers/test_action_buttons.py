from typing import Any
from unittest.mock import Mock

from canvas_sdk.effects import EffectType
from canvas_sdk.test_utils.factories import (
    LabPartnerFactory,
    LabPartnerTestFactory,
    NoteFactory,
    PatientFactory,
)
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note

from labcorp_draw_guidance.handlers.action_buttons import (
    BUTTON_KEY,
    LabOrderDrawGuidanceButton,
)


def _make_command(data: dict[str, Any], note: Note, patient: Any = None) -> Command:
    """Create a labOrder Command row directly since no CommandFactory exists in the SDK."""
    return Command.objects.create(
        note=note,
        patient=patient,
        state="staged",
        schema_key="labOrder",
        data=data,
        origination_source="",
        anchor_object_type="",
        anchor_object_dbid=0,
    )


def _make_button_event(note_dbid: int | None) -> Mock:
    mock_event = Mock()
    mock_event.context = {"note_id": note_dbid, "user": {"staff": "staff-key"}}
    return mock_event


def test_button_configuration() -> None:
    """Test that the button is configured with a title, key, note header location, and low sort priority."""
    assert LabOrderDrawGuidanceButton.BUTTON_KEY == BUTTON_KEY
    assert LabOrderDrawGuidanceButton.BUTTON_LOCATION == LabOrderDrawGuidanceButton.ButtonLocation.NOTE_HEADER
    assert LabOrderDrawGuidanceButton.BUTTON_TITLE
    assert LabOrderDrawGuidanceButton.PRIORITY == 9999


def test_button_is_always_visible() -> None:
    """Test that the button has no visible() override -- it always shows via the ActionButton default."""
    assert "visible" not in LabOrderDrawGuidanceButton.__dict__
    button = LabOrderDrawGuidanceButton(event=_make_button_event(None))

    assert button.visible() is True


def test_handle_launches_right_chart_pane_with_no_guidance_message_when_note_id_missing() -> None:
    """Test that handle() still returns a modal effect even without a note_id."""
    button = LabOrderDrawGuidanceButton(event=_make_button_event(None))

    effects = button.handle()

    assert len(effects) == 1
    assert effects[0].type == EffectType.LAUNCH_MODAL
    assert "No AccuDraw guidance currently available" in effects[0].payload


def test_handle_launches_right_chart_pane_with_tube_breakdown() -> None:
    """Test that handle() opens the right chart pane with the consolidated tube breakdown."""
    note = NoteFactory.create()
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="001453", order_name="CBC W/Diff")
    _make_command({"lab_partner": "Labcorp", "tests": ["001453"]}, note=note, patient=patient)

    button = LabOrderDrawGuidanceButton(event=_make_button_event(note.dbid))
    effects = button.handle()

    assert len(effects) == 1
    effect = effects[0]
    assert effect.type == EffectType.LAUNCH_MODAL
    assert "right_chart_pane" in effect.payload
    assert "Lavender (EDTA)" in effect.payload
    assert "CBC W/Diff" in effect.payload


def test_handle_lists_unresolved_tests() -> None:
    """Test that tests with no known tube guidance are called out in the panel HTML."""
    note = NoteFactory.create()
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="001453", order_name="CBC W/Diff")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="999999", order_name="Some Obscure Esoteric Panel")
    _make_command({"lab_partner": "Labcorp", "tests": ["001453", "999999"]}, note=note, patient=patient)

    button = LabOrderDrawGuidanceButton(event=_make_button_event(note.dbid))
    effects = button.handle()

    assert "Some Obscure Esoteric Panel" in effects[0].payload


def test_handle_covers_multiple_lab_order_commands_on_the_same_note() -> None:
    """Test that guidance for more than one lab order command on a note is all included."""
    note = NoteFactory.create()
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="001453", order_name="CBC W/Diff")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="322000", order_name="Lipid Panel")
    _make_command({"lab_partner": "Labcorp", "tests": ["001453"]}, note=note, patient=patient)
    _make_command({"lab_partner": "Labcorp", "tests": ["322000"]}, note=note, patient=patient)

    button = LabOrderDrawGuidanceButton(event=_make_button_event(note.dbid))
    effects = button.handle()

    assert "CBC W/Diff" in effects[0].payload
    assert "Lipid Panel" in effects[0].payload
