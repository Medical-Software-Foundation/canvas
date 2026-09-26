from typing import Any
from uuid import uuid4

from canvas_sdk.test_utils.factories import (
    LabPartnerFactory,
    LabPartnerTestFactory,
    NoteFactory,
    PatientFactory,
)
from canvas_sdk.v1.data.command import Command

from labcorp_draw_guidance.domain.order_resolution import (
    resolve_note_guidances,
    resolve_order_guidance,
)
from labcorp_draw_guidance.domain.tube_guidance import ConsolidatedTube


def _make_command(
    data: dict[str, Any], schema_key: str = "labOrder", patient: Any = None, note: Any = None
) -> Command:
    """Create a Command row directly since no CommandFactory exists in the SDK."""
    return Command.objects.create(
        note=note or NoteFactory.create(),
        patient=patient,
        state="staged",
        schema_key=schema_key,
        data=data,
        origination_source="",
        anchor_object_type="",
        anchor_object_dbid=0,
    )


def test_resolve_order_guidance_returns_none_for_non_lab_order_command() -> None:
    """Test that a command with a different schema_key is ignored."""
    patient = PatientFactory.create()
    command = _make_command({"lab_partner": "Labcorp", "tests": ["001453"]}, schema_key="diagnose", patient=patient)

    tested = resolve_order_guidance(command)

    assert tested is None


def test_resolve_order_guidance_returns_none_when_patient_missing() -> None:
    """Test that a command with no patient attached is ignored."""
    command = _make_command({"lab_partner": "Labcorp", "tests": ["001453"]}, patient=None)

    tested = resolve_order_guidance(command)

    assert tested is None


def test_resolve_order_guidance_returns_none_for_non_labcorp_partner() -> None:
    """Test that non-Labcorp lab partners are out of scope for v1."""
    patient = PatientFactory.create()
    command = _make_command({"lab_partner": "Quest Diagnostics", "tests": ["001453"]}, patient=patient)

    tested = resolve_order_guidance(command)

    assert tested is None


def test_resolve_order_guidance_returns_none_when_no_tests_staged() -> None:
    """Test that a Labcorp order with no tests yet returns no guidance."""
    patient = PatientFactory.create()
    command = _make_command({"lab_partner": "Labcorp", "tests": []}, patient=patient)

    tested = resolve_order_guidance(command)

    assert tested is None


def test_resolve_order_guidance_resolves_matched_test_by_order_code() -> None:
    """Test that a staged test matching by order_code resolves to consolidated guidance."""
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="001453", order_name="CBC W/Diff")
    command = _make_command({"lab_partner": "Labcorp", "tests": ["001453"]}, patient=patient)

    tested = resolve_order_guidance(command)

    assert tested is not None
    assert tested.consolidated == (
        ConsolidatedTube(
            tube_type="Lavender (EDTA)",
            tube_count=1,
            draw_volume_ml=3.0,
            tests=("CBC W/Diff",),
        ),
    )
    assert tested.unresolved_test_names == ()


def test_resolve_order_guidance_resolves_matched_test_by_id() -> None:
    """Test that a staged test identified by LabPartnerTest id (not order_code) still resolves."""
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    lab_test = LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="322000", order_name="Lipid Panel")
    command = _make_command({"lab_partner": "Labcorp", "tests": [str(lab_test.id)]}, patient=patient)

    tested = resolve_order_guidance(command)

    assert tested is not None
    assert tested.consolidated == (
        ConsolidatedTube(
            tube_type="Gold (SST)",
            tube_count=1,
            draw_volume_ml=3.5,
            tests=("Lipid Panel",),
        ),
    )


def test_resolve_order_guidance_returns_none_when_no_matched_test_has_known_guidance() -> None:
    """Test that a matched but unrecognized test yields no guidance (no card should show)."""
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="999999", order_name="Some Obscure Esoteric Panel")
    command = _make_command({"lab_partner": "Labcorp", "tests": ["999999"]}, patient=patient)

    tested = resolve_order_guidance(command)

    assert tested is None


def test_resolve_order_guidance_tracks_unresolved_alongside_resolved_tests() -> None:
    """Test that a mix of known and unknown tests yields guidance plus an unresolved list."""
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="001453", order_name="CBC W/Diff")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="999999", order_name="Some Obscure Esoteric Panel")
    command = _make_command({"lab_partner": "Labcorp", "tests": ["001453", "999999"]}, patient=patient)

    tested = resolve_order_guidance(command)

    assert tested is not None
    assert tested.unresolved_test_names == ("Some Obscure Esoteric Panel",)
    assert len(tested.consolidated) == 1


def test_resolve_note_guidances_returns_empty_list_when_no_qualifying_commands() -> None:
    """Test that a note with no qualifying lab order commands resolves to an empty list."""
    note = NoteFactory.create()
    patient = PatientFactory.create()
    _make_command({"lab_partner": "Quest Diagnostics", "tests": ["001453"]}, patient=patient, note=note)

    tested = resolve_note_guidances(note.dbid)

    assert tested == []


def test_resolve_note_guidances_matches_single_command_by_id() -> None:
    """Test that the batched note-level lookup still matches tests identified by LabPartnerTest id."""
    note = NoteFactory.create()
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    lab_test = LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="322000", order_name="Lipid Panel")
    _make_command({"lab_partner": "Labcorp", "tests": [str(lab_test.id)]}, patient=patient, note=note)

    tested = resolve_note_guidances(note.dbid)

    assert len(tested) == 1
    assert tested[0].consolidated == (
        ConsolidatedTube(tube_type="Gold (SST)", tube_count=1, draw_volume_ml=3.5, tests=("Lipid Panel",)),
    )


def test_resolve_note_guidances_groups_matches_back_to_the_right_command() -> None:
    """Test that batching the LabPartnerTest lookup across commands still attributes tests correctly."""
    note = NoteFactory.create()
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="001453", order_name="CBC W/Diff")
    lipid_test = LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="322000", order_name="Lipid Panel")
    _make_command({"lab_partner": "Labcorp", "tests": ["001453"]}, patient=patient, note=note)
    _make_command({"lab_partner": "Labcorp", "tests": [str(lipid_test.id)]}, patient=patient, note=note)
    _make_command({"lab_partner": "Quest Diagnostics", "tests": ["001453"]}, patient=patient, note=note)

    tested = resolve_note_guidances(note.dbid)

    tube_types = {tube.tube_type for guidance in tested for tube in guidance.consolidated}
    assert len(tested) == 2
    assert tube_types == {"Lavender (EDTA)", "Gold (SST)"}


def test_resolve_note_guidances_skips_commands_that_qualify_but_resolve_to_no_guidance() -> None:
    """Test that a qualifying command whose identifiers match nothing is excluded, not errored."""
    note = NoteFactory.create()
    patient = PatientFactory.create()
    lab_partner = LabPartnerFactory.create(name="Labcorp")
    LabPartnerTestFactory.create(lab_partner=lab_partner, order_code="001453", order_name="CBC W/Diff")
    unmatched_uuid = uuid4()
    _make_command(
        {"lab_partner": "Labcorp", "tests": ["no-such-code", str(unmatched_uuid)]}, patient=patient, note=note
    )
    _make_command({"lab_partner": "Labcorp", "tests": ["001453"]}, patient=patient, note=note)

    tested = resolve_note_guidances(note.dbid)

    assert len(tested) == 1
    assert tested[0].consolidated[0].tube_type == "Lavender (EDTA)"
