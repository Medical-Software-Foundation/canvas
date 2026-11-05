from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.events import EventType

from charting_tools.handlers.appointment_created import AppointmentCreatedTemplate
from charting_tools.handlers.note_created import NoteCreatedTemplate
from charting_tools.insertion import APPLIED_METADATA_KEY, TEMPLATE_COMMAND_KEY
from charting_tools.note_types import note_type_options, template_for_note_type
from tests.conftest import make_template, payload

INSERTION = "charting_tools.insertion"
NOTE_ID = "3f2b8a1c9d4e4f60a7b8c9d0e1f2a3b4"


def _event(event_type: int, target_id: str = "t" * 32) -> SimpleNamespace:
    return SimpleNamespace(
        type=event_type, name=EventType.Name(event_type), context={}, target=SimpleNamespace(id=target_id)
    )


def _note(unique_identifier: str | None = "type-office") -> SimpleNamespace:
    note_type = SimpleNamespace(unique_identifier=unique_identifier) if unique_identifier else None
    return SimpleNamespace(id=NOTE_ID, dbid=5, patient_id=1, datetime_of_service="x", note_type_version=note_type)


OFFICE = make_template(
    template_id="office",
    note_types=[{"unique_identifier": "type-office", "name": "Office visit"}],
    commands=[{"schema_key": "hpi"}, {"schema_key": "plan"}],
)


@pytest.fixture
def templates(mocker: MagicMock) -> MagicMock:
    query = mocker.patch(f"{INSERTION}.NoteTemplate.objects.filter")
    query.return_value.exclude.return_value.order_by.return_value = [make_template(template_id="other", note_types=[]), OFFICE]
    return query


@pytest.fixture
def not_applied(mocker: MagicMock) -> MagicMock:
    # The metadata effect checks the note exists before it builds.
    mocker.patch(
        "canvas_sdk.effects.note_metadata.base.Note.objects.filter"
    ).return_value.exists.return_value = True
    query = mocker.patch(f"{INSERTION}.NoteMetadata.objects.filter")
    query.return_value.exists.return_value = False
    return query


def _assert_appended(effects: list, note_id: str = NOTE_ID) -> None:
    assert [e.type for e in effects] == [
        EffectType.BATCH_ORIGINATE_COMMANDS,
        EffectType.UPSERT_COMMAND_METADATA,
        EffectType.UPSERT_COMMAND_METADATA,
        EffectType.UPSERT_NOTE_METADATA,
    ]
    # Each inserted command is tagged with the template, for a later visit type change.
    tags = [payload(e)["data"] for e in effects[1:3]]
    assert [(t["key"], t["value"]) for t in tags] == [(TEMPLATE_COMMAND_KEY, "office")] * 2
    data = payload(effects[0])["data"]
    assert data["replace_line"] is False
    assert data["line_number"] == -1
    assert [c["type"] for c in data["commands"]] == ["ORIGINATE_HPI_COMMAND", "ORIGINATE_PLAN_COMMAND"]
    marker = payload(effects[-1])["data"]
    assert marker["key"] == APPLIED_METADATA_KEY
    assert marker["value"] == "office"
    assert marker["note_id"] == note_id


class TestNoteCreated:
    def _patch_note(self, mocker: MagicMock, note: SimpleNamespace | None) -> None:
        mocker.patch(
            "charting_tools.handlers.note_created.Note.objects.select_related"
        ).return_value.defer.return_value.filter.return_value.first.return_value = note

    def test_appends_template_for_note_type(
        self, mocker: MagicMock, templates: MagicMock, not_applied: MagicMock
    ) -> None:
        self._patch_note(mocker, _note())
        effects = NoteCreatedTemplate(event=_event(EventType.NOTE_CREATED)).compute()
        templates.assert_called_once_with(active=True)
        not_applied.assert_called_once_with(note_id=5, key=APPLIED_METADATA_KEY)
        _assert_appended(effects)

    def test_template_hidden_from_menu_still_applies(
        self, mocker: MagicMock, not_applied: MagicMock
    ) -> None:
        template = make_template(
            show_in_menu=False, note_types=[{"unique_identifier": "type-office"}], commands=[{"schema_key": "plan"}]
        )
        mocker.patch(f"{INSERTION}.NoteTemplate.objects.filter").return_value.exclude.return_value.order_by.return_value = [template]
        self._patch_note(mocker, _note())
        assert len(NoteCreatedTemplate(event=_event(EventType.NOTE_CREATED)).compute()) == 3

    def test_appointment_type_note_is_left_for_booking_handler(
        self, mocker: MagicMock, templates: MagicMock, not_applied: MagicMock
    ) -> None:
        self._patch_note(mocker, _note("type-appointment"))
        assert NoteCreatedTemplate(event=_event(EventType.NOTE_CREATED)).compute() == []
        not_applied.assert_not_called()

    def test_null_note_types_column(self, mocker: MagicMock, not_applied: MagicMock) -> None:
        mocker.patch(f"{INSERTION}.NoteTemplate.objects.filter").return_value.exclude.return_value.order_by.return_value = [
            make_template(note_types=None)
        ]
        self._patch_note(mocker, _note())
        assert NoteCreatedTemplate(event=_event(EventType.NOTE_CREATED)).compute() == []

    def test_missing_note(self, mocker: MagicMock, templates: MagicMock) -> None:
        self._patch_note(mocker, None)
        assert NoteCreatedTemplate(event=_event(EventType.NOTE_CREATED)).compute() == []
        templates.assert_not_called()


class TestAppointmentCreated:
    @pytest.fixture(autouse=True)
    def applied(self, mocker: MagicMock) -> MagicMock:
        query = mocker.patch("charting_tools.handlers.appointment_created.NoteMetadata.objects.filter")
        query.return_value.exists.return_value = False
        return query

    def _patch_appointment(self, mocker: MagicMock, appointment: SimpleNamespace | None) -> MagicMock:
        query = mocker.patch("charting_tools.handlers.appointment_created.Appointment.objects.select_related")
        query.return_value.defer.return_value.filter.return_value.first.return_value = appointment
        return query

    def _appointment(self, **overrides: object) -> SimpleNamespace:
        fields = {
            "note": _note("type-appointment"),  # booked notes carry the generic Appointment type
            "note_type": SimpleNamespace(unique_identifier="type-office"),
        }
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def test_booking_applies_template_for_appointment_note_type(
        self, mocker: MagicMock, templates: MagicMock, not_applied: MagicMock
    ) -> None:
        query = self._patch_appointment(mocker, self._appointment())
        effects = AppointmentCreatedTemplate(event=_event(EventType.APPOINTMENT_CREATED, "appt1")).compute()
        query.return_value.defer.return_value.filter.assert_called_once_with(id="appt1", entered_in_error__isnull=True)
        _assert_appended(effects)

    def test_reschedule_onto_same_note_switches_template(
        self, mocker: MagicMock, templates: MagicMock, applied: MagicMock
    ) -> None:
        applied.return_value.exists.return_value = True
        switch = mocker.patch("charting_tools.handlers.appointment_created.switch_template", return_value=["swapped"])
        appointment = self._appointment()
        self._patch_appointment(mocker, appointment)
        assert AppointmentCreatedTemplate(event=_event(EventType.APPOINTMENT_CREATED)).compute() == ["swapped"]
        switch.assert_called_once_with(appointment.note, "type-office", {})

    @pytest.mark.parametrize("missing", ["note", "note_type"])
    def test_schedule_events_without_note_are_skipped(
        self, mocker: MagicMock, templates: MagicMock, missing: str
    ) -> None:
        self._patch_appointment(mocker, self._appointment(**{missing: None}))
        assert AppointmentCreatedTemplate(event=_event(EventType.APPOINTMENT_CREATED)).compute() == []
        templates.assert_not_called()

    def test_visit_type_without_a_template_is_marked(
        self, mocker: MagicMock, templates: MagicMock, not_applied: MagicMock
    ) -> None:
        # Booked as a type with no template: marked "none", so changing the
        # visit type later brings in the new type's template.
        self._patch_appointment(mocker, self._appointment(note_type=SimpleNamespace(unique_identifier="type-phone")))
        [marker] = AppointmentCreatedTemplate(event=_event(EventType.APPOINTMENT_CREATED)).compute()
        data = payload(marker)["data"]
        assert (data["key"], data["value"]) == (APPLIED_METADATA_KEY, "none")

    def test_note_created_directly_with_no_template_is_not_marked(
        self, mocker: MagicMock, templates: MagicMock, not_applied: MagicMock
    ) -> None:
        from charting_tools.insertion import auto_apply

        assert auto_apply(_note("type-phone"), "type-phone", {}) == []

    def test_missing_appointment(self, mocker: MagicMock, templates: MagicMock) -> None:
        self._patch_appointment(mocker, None)
        assert AppointmentCreatedTemplate(event=_event(EventType.APPOINTMENT_CREATED)).compute() == []


def test_template_for_note_type_first_match_wins() -> None:
    a = make_template(template_id="a", note_types=[{"unique_identifier": "x"}])
    b = make_template(template_id="b", note_types=[{"unique_identifier": "x"}])
    assert template_for_note_type([a, b], "x") is a
    assert template_for_note_type([a, b], "y") is None


def test_note_type_options_are_current_charting_types(mocker: MagicMock) -> None:
    query = mocker.patch("charting_tools.note_types.NoteType.objects.filter")
    query.return_value.order_by.return_value.values.return_value = [{"unique_identifier": "u1", "name": "Office visit"}]
    assert note_type_options() == [{"unique_identifier": "u1", "name": "Office visit"}]
    kwargs = query.call_args.kwargs
    assert kwargs["is_active"] is True
    assert kwargs["deprecated_at__isnull"] is True
    assert set(kwargs["category__in"]) == {"encounter", "inpatient", "review"}
