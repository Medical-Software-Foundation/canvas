"""Refreshing the waitlist buttons after a write.

Both buttons decide their label when they render, and nothing redraws them on
their own. The chart header and a note header are separate effects in the SDK;
emitting only the first is why a note's label stayed stale until the page was
reloaded while the chart updated immediately.
"""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.services.chart_buttons import (
    MAX_NOTE_RELOADS,
    reload_chart_buttons,
)

MODULE = "scheduling_waitlist.services.chart_buttons"


def _entry(patient_id="patient-uuid", patient_dbid=55, note_type_id=7):
    entry = MagicMock()
    entry.patient = MagicMock(id=patient_id, dbid=patient_dbid)
    entry.note_type_id = note_type_id
    return entry


def _appointment(note_id="note-uuid", status="cancelled", note_state="NEW"):
    record = MagicMock()
    record.status = status
    record.note = MagicMock(id=note_id, current_state=MagicMock(state=note_state))
    return record


def _appointments(found):
    """Patch the Appointment lookup so the chain resolves to ``found``."""
    model = MagicMock()
    window = model.objects.filter.return_value.select_related.return_value.order_by.return_value
    window.__getitem__.return_value = found
    return model


def _reload(entry, found=()):
    with patch(f"{MODULE}.Appointment", _appointments(list(found))):
        return reload_chart_buttons(entry)


class TestTheChartHeader:
    def test_the_patients_chart_is_asked_to_redraw(self):
        effects = _reload(_entry("abc-123"))

        assert len(effects) == 1
        assert effects[0].id == "abc-123"

    def test_the_identifier_is_sent_as_text(self):
        # The effect addresses a chart by key, not by row id.
        assert _reload(_entry(patient_id=12345))[0].id == "12345"

    def test_the_chart_comes_first(self):
        # It is the surface most likely to be on screen when the write happens.
        effects = _reload(_entry("abc-123"), found=[_appointment()])

        assert effects[0].id == "abc-123"


class TestGuards:
    def test_an_entry_with_no_patient_refreshes_nothing(self):
        entry = MagicMock()
        entry.patient = None

        assert _reload(entry) == []

    def test_a_patient_without_a_key_refreshes_nothing(self):
        assert _reload(_entry(patient_id=None)) == []

    def test_a_missing_entry_refreshes_nothing(self):
        assert _reload(None) == []


class TestNoteHeaders:
    """The half that was missing."""

    def test_a_freed_appointments_note_is_asked_to_redraw(self):
        effects = _reload(_entry(), found=[_appointment(note_id="n1")])

        assert [e.id for e in effects[1:]] == ["n1"]

    def test_a_note_freed_only_by_its_state_still_counts(self):
        # Marking no-show moves the note's state; whether it also moves the
        # appointment's status is not something a plugin can see.
        effects = _reload(
            _entry(), found=[_appointment(note_id="n1", status="confirmed", note_state="NSW")]
        )

        assert [e.id for e in effects[1:]] == ["n1"]

    def test_a_still_booked_appointment_is_left_alone(self):
        # Its note carries no waitlist button, so redrawing it changes nothing.
        effects = _reload(
            _entry(), found=[_appointment(status="confirmed", note_state="NEW")]
        )

        assert len(effects) == 1

    def test_an_appointment_whose_note_has_no_key_is_skipped(self):
        effects = _reload(_entry(), found=[_appointment(note_id=None)])

        assert len(effects) == 1

    def test_several_freed_notes_are_all_redrawn(self):
        found = [_appointment(note_id="n1"), _appointment(note_id="n2")]

        effects = _reload(_entry(), found=found)

        assert [e.id for e in effects[1:]] == ["n1", "n2"]


class TestNarrowing:
    def test_only_this_patients_appointments_are_considered(self):
        model = _appointments([])
        with patch(f"{MODULE}.Appointment", model):
            reload_chart_buttons(_entry(patient_dbid=55))

        assert model.objects.filter.call_args.kwargs["patient_id"] == 55

    def test_only_this_entrys_service_is_considered(self):
        # The note button asks about *this slot's* service, so a change to a
        # Follow-up entry cannot alter the label on a cancelled Physical.
        model = _appointments([])
        with patch(f"{MODULE}.Appointment", model):
            reload_chart_buttons(_entry(note_type_id=7))

        assert model.objects.filter.call_args.kwargs["note_type_id"] == 7

    def test_appointments_marked_entered_in_error_are_excluded(self):
        model = _appointments([])
        with patch(f"{MODULE}.Appointment", model):
            reload_chart_buttons(_entry())

        assert model.objects.filter.call_args.kwargs["entered_in_error__isnull"] is True

    def test_an_any_service_entry_reloads_no_notes(self):
        # There is no single service to narrow by, and reloading a patient's whole
        # cancellation history on one write is worse than a stale label.
        effects = _reload(_entry(note_type_id=None), found=[_appointment()])

        assert len(effects) == 1

    def test_the_note_state_is_selected_with_the_appointment(self):
        model = _appointments([])
        with patch(f"{MODULE}.Appointment", model):
            reload_chart_buttons(_entry())

        assert (
            "note__current_state"
            in model.objects.filter.return_value.select_related.call_args.args
        )

    def test_the_number_of_notes_is_capped(self):
        model = _appointments([])
        with patch(f"{MODULE}.Appointment", model):
            reload_chart_buttons(_entry())

        window = model.objects.filter.return_value.select_related.return_value.order_by.return_value
        assert window.__getitem__.call_args.args[0] == slice(None, MAX_NOTE_RELOADS)
