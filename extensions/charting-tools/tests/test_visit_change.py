from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.events import EventType

from charting_tools.handlers.appointment_created import AppointmentUpdatedTemplate
from charting_tools.insertion import APPLIED_METADATA_KEY, TEMPLATE_COMMAND_KEY
from charting_tools.visit_change import NO_TEMPLATE, switch_template, unchanged
from tests.conftest import make_template, payload

VC = "charting_tools.visit_change"
NOTE = SimpleNamespace(id="3f2b8a1c9d4e4f60a7b8c9d0e1f2a3b4", dbid=5, patient_id=1, datetime_of_service=None)
PHQ9 = {"code_system": "LOINC", "code": "44249-1"}
GAD7 = {"code_system": "LOINC", "code": "69737-5"}
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)

OFFICE = make_template(
    template_id="office",
    note_types=[{"unique_identifier": "type-office"}],
    commands=[{"schema_key": "hpi"}, {"schema_key": "plan"}, {"schema_key": "questionnaire", "questionnaire": PHQ9}],
)
PHYSICAL = make_template(
    template_id="physical",
    note_types=[{"unique_identifier": "type-physical"}],
    commands=[{"schema_key": "hpi"}, {"schema_key": "ros"}, {"schema_key": "questionnaire", "questionnaire": GAD7}],
)


def _row(dbid: int, schema_key: str, *, edited: float = 0, state: str = "staged", committed: bool = False,
         questionnaire: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        dbid=dbid,
        id=f"{dbid:032x}",
        schema_key=schema_key,
        state=state,
        committer_id=9 if committed else None,
        created=T0,
        modified=T0 + timedelta(seconds=edited),
        data={"questionnaire": {"value": questionnaire}} if questionnaire else {},
    )


@pytest.fixture
def note_state(mocker: MagicMock) -> MagicMock:
    query = mocker.patch(f"{VC}.CurrentNoteStateEvent.objects.filter")
    query.return_value.values_list.return_value.first.return_value = "BKD"
    return query


@pytest.fixture
def db(mocker: MagicMock, note_state: MagicMock) -> SimpleNamespace:
    marker = mocker.patch(f"{VC}.NoteMetadata.objects.filter")
    marker.return_value.first.return_value = SimpleNamespace(value="office")
    templates = mocker.patch(f"{VC}.NoteTemplate.objects.filter")
    templates.return_value.exclude.return_value.order_by.return_value = [OFFICE, PHYSICAL]
    tagged = mocker.patch(f"{VC}.CommandMetadata.objects.filter")
    tagged.return_value.exists.return_value = True
    commands = mocker.patch(f"{VC}.Command.objects.filter")
    questionnaires = mocker.patch(f"{VC}.Questionnaire.objects.filter")
    questionnaires.return_value.values_list.return_value = [(301, *PHQ9.values()), (302, *GAD7.values())]
    mocker.patch(f"{VC}.build_commands", side_effect=lambda template, note: [
        SimpleNamespace(command=SimpleNamespace(schema_key=e["schema_key"]), entries=e) for e in template.commands
    ])
    originate = mocker.patch(f"{VC}.originate_effects", return_value=["originated"])
    mocker.patch(
        "canvas_sdk.effects.note_metadata.base.Note.objects.filter"
    ).return_value.exists.return_value = True
    return SimpleNamespace(marker=marker, commands=commands, tagged=tagged, originate=originate)


def _rows(db: SimpleNamespace, rows: list) -> None:
    db.commands.return_value.exclude.return_value.order_by.return_value = rows


def _deleted(effects: list) -> list[str]:
    return [
        payload(e)["command"]
        for e in effects
        if not isinstance(e, str) and EffectType.Name(e.type).startswith("DELETE_")
    ]


def _added(db: SimpleNamespace) -> list[str]:
    if not db.originate.called:
        return []
    return [b.command.schema_key for b in db.originate.call_args.args[0]]


def test_shared_kept_unchanged_extras_removed_new_ones_added(db: SimpleNamespace) -> None:
    _rows(db, [_row(1, "hpi"), _row(2, "plan"), _row(3, "questionnaire", questionnaire=301)])
    effects = switch_template(NOTE, "type-physical", {})

    # HPI is in both templates; Plan and the PHQ-9 are office-only and untouched.
    assert _deleted(effects) == [f"{2:032x}", f"{3:032x}"]
    assert _added(db) == ["ros", "questionnaire"]
    assert db.originate.call_args.kwargs["template_tag"] == "physical"
    marker = payload(effects[-1])["data"]
    assert (marker["key"], marker["value"]) == (APPLIED_METADATA_KEY, "physical")
    # Only commands the template inserted are considered.
    assert db.commands.call_args.kwargs["metadata__key"] == TEMPLATE_COMMAND_KEY


def test_edited_and_committed_commands_stay(db: SimpleNamespace) -> None:
    _rows(db, [
        _row(1, "hpi"),
        _row(2, "plan", edited=40),                      # someone typed in it
        _row(3, "questionnaire", questionnaire=301, committed=True, state="committed"),
    ])
    assert _deleted(switch_template(NOTE, "type-physical", {})) == []


def test_saves_within_tolerance_still_count_as_unchanged() -> None:
    assert unchanged(_row(1, "plan", edited=4))
    assert not unchanged(_row(1, "plan", edited=6))
    assert not unchanged(_row(1, "plan", committed=True))


def test_same_questionnaire_is_shared_by_code(db: SimpleNamespace) -> None:
    db.marker.return_value.first.return_value = SimpleNamespace(value="physical")
    _rows(db, [_row(1, "hpi"), _row(2, "ros"), _row(3, "questionnaire", questionnaire=302)])
    other = make_template(
        template_id="followup",
        note_types=[{"unique_identifier": "type-followup"}],
        commands=[{"schema_key": "questionnaire", "questionnaire": GAD7}],
    )
    from charting_tools import visit_change

    visit_change.NoteTemplate.objects.filter.return_value.exclude.return_value.order_by.return_value = [other]
    effects = switch_template(NOTE, "type-followup", {})
    assert _deleted(effects) == [f"{1:032x}", f"{2:032x}"]  # GAD-7 kept
    assert _added(db) == []


def test_edited_duplicate_claims_the_shared_place(db: SimpleNamespace) -> None:
    db.marker.return_value.first.return_value = SimpleNamespace(value="two-plans")
    _rows(db, [_row(1, "plan"), _row(2, "plan", edited=30)])
    one_plan = make_template(template_id="one", note_types=[{"unique_identifier": "type-one"}],
                             commands=[{"schema_key": "plan"}])
    from charting_tools import visit_change

    visit_change.NoteTemplate.objects.filter.return_value.exclude.return_value.order_by.return_value = [one_plan]
    assert _deleted(switch_template(NOTE, "type-one", {})) == [f"{1:032x}"]


def test_new_visit_type_without_template_removes_unchanged(db: SimpleNamespace) -> None:
    _rows(db, [_row(1, "hpi"), _row(2, "plan", edited=60)])
    effects = switch_template(NOTE, "type-phone", {})
    assert _deleted(effects) == [f"{1:032x}"]
    assert _added(db) == []
    assert payload(effects[-1])["data"]["value"] == NO_TEMPLATE


def test_same_template_does_nothing(db: SimpleNamespace) -> None:
    assert switch_template(NOTE, "type-office", {}) == []
    db.commands.assert_not_called()


def test_notes_without_automatic_template_are_left_alone(db: SimpleNamespace) -> None:
    db.marker.return_value.first.return_value = None
    assert switch_template(NOTE, "type-physical", {}) == []


def test_notes_from_before_tagging_are_left_alone(db: SimpleNamespace) -> None:
    db.tagged.return_value.exists.return_value = False
    assert switch_template(NOTE, "type-physical", {}) == []
    db.commands.assert_not_called()


@pytest.mark.parametrize("state", ["LKD", "SGN", "DLT", None])
def test_locked_signed_or_deleted_notes_are_left_alone(db: SimpleNamespace, note_state: MagicMock, state: str) -> None:
    note_state.return_value.values_list.return_value.first.return_value = state
    assert switch_template(NOTE, "type-physical", {}) == []


class TestAppointmentUpdated:
    H = "charting_tools.handlers.appointment_created"

    def _run(self, mocker: MagicMock, appointment: SimpleNamespace, latest: str) -> tuple[list, MagicMock]:
        mocker.patch(f"{self.H}.Appointment.objects.select_related").return_value.defer.return_value.filter.return_value.first.return_value = appointment
        mocker.patch(
            f"{self.H}.Appointment.objects.filter"
        ).return_value.order_by.return_value.values_list.return_value.first.return_value = latest
        switch = mocker.patch(f"{self.H}.switch_template", return_value=["swapped"])
        event = SimpleNamespace(type=EventType.APPOINTMENT_UPDATED, name="APPOINTMENT_UPDATED", context={},
                                target=SimpleNamespace(id=appointment.id))
        return AppointmentUpdatedTemplate(event=event).compute(), switch

    def _appointment(self, **overrides: object) -> SimpleNamespace:
        fields = {"id": "appt2", "note": NOTE, "status": "confirmed",
                  "note_type": SimpleNamespace(unique_identifier="type-physical")}
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def test_current_appointment_switches(self, mocker: MagicMock) -> None:
        effects, switch = self._run(mocker, self._appointment(), latest="appt2")
        assert effects == ["swapped"]
        switch.assert_called_once_with(NOTE, "type-physical", {})

    def test_replaced_appointment_is_ignored(self, mocker: MagicMock) -> None:
        # A reschedule also updates the old appointment, which has the old type.
        effects, switch = self._run(mocker, self._appointment(id="appt1"), latest="appt2")
        assert effects == []
        switch.assert_not_called()

    @pytest.mark.parametrize("status", ["cancelled", "noshowed"])
    def test_canceled_or_no_show_is_ignored(self, mocker: MagicMock, status: str) -> None:
        effects, switch = self._run(mocker, self._appointment(status=status), latest="appt2")
        assert effects == []
        switch.assert_not_called()


def test_visit_booked_without_a_template_gets_the_new_types_template(db: SimpleNamespace) -> None:
    # Booked as a type with no template (marked "none"), then changed to one with a template.
    db.marker.return_value.first.return_value = SimpleNamespace(value=NO_TEMPLATE)
    db.tagged.return_value.exists.return_value = False  # nothing was inserted at booking
    _rows(db, [])
    effects = switch_template(NOTE, "type-physical", {})
    assert _deleted(effects) == []
    assert _added(db) == ["hpi", "ros", "questionnaire"]
    assert db.originate.call_args.kwargs["template_tag"] == "physical"
    marker = payload(effects[-1])["data"]
    assert (marker["key"], marker["value"]) == (APPLIED_METADATA_KEY, "physical")


def test_visit_booked_without_a_template_changed_to_another_without_one(db: SimpleNamespace) -> None:
    db.marker.return_value.first.return_value = SimpleNamespace(value=NO_TEMPLATE)
    assert switch_template(NOTE, "type-phone", {}) == []
