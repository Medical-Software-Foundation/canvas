"""Redrawing a note's buttons when its state changes.

An ActionButton decides visibility as the note renders, so a no-show left "Add to
waitlist" absent until the page was reloaded. These tests pin the redraw, and pin
the two reasons it must *not* fire: an unresolvable note, and a note with no
appointment behind it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.note_buttons import NoteButtonsRefreshHandler

MODULE = "scheduling_waitlist.handlers.note_buttons"


def make_event(target_id="change-uuid", context=None):
    return SimpleNamespace(
        target=SimpleNamespace(id=target_id), context=context if context is not None else {}
    )


def run(
    *,
    event=None,
    state_change=None,
    note=None,
    has_appointment=True,
):
    """Drive the handler with each lookup scripted independently."""
    handler = NoteButtonsRefreshHandler(event=event or make_event())

    change_model = MagicMock()
    change_model.objects.filter.return_value.select_related.return_value.first.return_value = (
        state_change
    )

    note_model = MagicMock()
    note_model.objects.filter.return_value.first.return_value = note

    appointment_model = MagicMock()
    appointment_model.objects.filter.return_value.exists.return_value = has_appointment

    with (
        patch(f"{MODULE}.NoteStateChangeEvent", change_model),
        patch(f"{MODULE}.Note", note_model),
        patch(f"{MODULE}.Appointment", appointment_model),
    ):
        return handler.compute(), appointment_model


def a_note(dbid=41, id="note-uuid"):  # noqa: A002 - mirrors the model's field name
    return SimpleNamespace(dbid=dbid, id=id)


class TestTheRedraw:
    def test_a_state_change_redraws_its_notes_buttons(self):
        # The whole point: marking no-show must not need a page reload.
        effects, _ = run(state_change=SimpleNamespace(note=a_note()))

        assert len(effects) == 1
        assert effects[0].id == "note-uuid"

    def test_the_note_is_addressed_by_its_uuid_not_its_dbid(self):
        # The effect validates the id against Note.id, which is a UUID. Passing
        # the dbid the button handler receives would fail on the instance while
        # looking perfectly reasonable here.
        effects, _ = run(state_change=SimpleNamespace(note=a_note(dbid=41, id="note-uuid")))

        assert effects[0].id == "note-uuid"

    def test_an_identifier_naming_the_note_itself_still_resolves(self):
        # Nothing documents whether the event names the state-change row or the
        # note, so the fallback has to work rather than be decorative.
        effects, _ = run(state_change=None, note=a_note())

        assert len(effects) == 1

    def test_the_state_change_row_is_preferred_over_the_note_lookup(self):
        effects, _ = run(
            state_change=SimpleNamespace(note=a_note(id="from-change")),
            note=a_note(id="from-note"),
        )

        assert effects[0].id == "from-change"


class TestWhenItStaysQuiet:
    def test_a_note_with_no_appointment_is_left_alone(self):
        # A progress note being signed cannot show this button, so redrawing it
        # would be an effect per note in the instance.
        effects, _ = run(state_change=SimpleNamespace(note=a_note()), has_appointment=False)

        assert effects == []

    def test_a_retracted_appointment_does_not_count(self):
        _, appointment_model = run(state_change=SimpleNamespace(note=a_note()))

        assert appointment_model.objects.filter.call_args.kwargs == {
            "note__dbid": 41,
            "entered_in_error__isnull": True,
        }

    def test_an_event_with_no_identifier_does_nothing(self):
        effects, _ = run(event=make_event(target_id=None))

        assert effects == []

    def test_an_unresolvable_identifier_does_nothing(self):
        effects, _ = run(state_change=None, note=None)

        assert effects == []

    def test_a_state_change_with_no_note_attached_does_nothing(self):
        effects, _ = run(state_change=SimpleNamespace(note=None))

        assert effects == []

    def test_a_note_without_a_dbid_is_not_queried_for_appointments(self):
        # Filtering on note__dbid=None matches arbitrary rows rather than none.
        effects, appointment_model = run(
            state_change=SimpleNamespace(note=SimpleNamespace(dbid=None, id="note-uuid"))
        )

        assert effects == []
        appointment_model.objects.filter.assert_not_called()

    def test_a_note_without_an_id_raises_no_effect(self):
        effects, _ = run(
            state_change=SimpleNamespace(note=SimpleNamespace(dbid=41, id=None))
        )

        assert effects == []


class TestSubscription:
    def test_it_listens_for_the_note_state_change(self):
        # Not APPOINTMENT_NO_SHOWED: a UI no-show does not emit that event, which
        # is why the button used to need a reload.
        assert NoteButtonsRefreshHandler.RESPONDS_TO == "NOTE_STATE_CHANGE_EVENT_CREATED"

    def test_it_does_not_filter_by_which_state_was_entered(self):
        """Leaving cancelled/no-showed must hide the button again.

        Enumerating the states that lead *out* -- reverted, restored, undeleted --
        is a list that goes stale silently, and an extra redraw is cheaper than a
        button that lies. So a state this plugin has no interest in still redraws.
        """
        effects, _ = run(
            event=make_event(),
            state_change=SimpleNamespace(note=a_note(), state="SGN"),
        )

        assert len(effects) == 1
