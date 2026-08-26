"""The chart button that puts the patient in front of you on the waitlist.

The banner answers "is this patient waiting?". This button answers "put them on
the list" -- a different question, and one a passive banner cannot serve. Without
it a scheduler looking at a chart has to open the provider menu and search for the
patient they are already looking at.

It writes on click rather than opening a form. Every field on that form already
defaulted to its broadest setting, so the modal was confirming answers that were
correct on arrival -- and a second button offering the shortcut alongside it was
worse than either, because a chart header truncates labels at roughly twelve
characters and the two came out indistinguishable.
"""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.chart_button import AddToWaitlistButton
from scheduling_waitlist.services.entries import DuplicateEntryError
from scheduling_waitlist.services.quick_add import QuickAddRefused

MODULE = "scheduling_waitlist.handlers.chart_button"

# Distinguishes "the test did not care" from "the test means None". An
# unresolvable staff member is the interesting case, so it cannot be the default.
UNSET = object()


def _button(patient_id="patient-uuid", actor_id=7):
    button = AddToWaitlistButton.__new__(AddToWaitlistButton)
    event = MagicMock()
    event.target.id = patient_id
    event.actor.id = actor_id
    button.event = event
    button.secrets = {}
    return button


def _patient_model(found=True, patient_id="patient-uuid", dbid=55):
    model = MagicMock()
    record = MagicMock(dbid=dbid) if found else None
    if record is not None:
        record.id = patient_id
    model.objects.filter.return_value.only.return_value.first.return_value = record
    return model


def _for_button(button):
    return _patient_model(patient_id=button.event.target.id)


def _visible(button, listed=False, patient=None):
    with (
        patch(f"{MODULE}.Patient", patient or _for_button(button)),
        patch(f"{MODULE}.has_live_entry", return_value=listed),
    ):
        return button.visible()


def _click(
    button,
    *,
    listed=False,
    staff=UNSET,
    error=None,
    patient=None,
):
    """Run the click with every collaborator stubbed, returning the effects."""
    entry = MagicMock(dbid=900)
    with (
        patch(f"{MODULE}.Patient", patient or _for_button(button)),
        patch(f"{MODULE}.has_live_entry", return_value=listed),
        patch(
            f"{MODULE}.staff_from_actor",
            return_value=MagicMock(dbid=101) if staff is UNSET else staff,
        ),
        patch(f"{MODULE}.quick_add", side_effect=error, return_value=entry) as writer,
        patch(f"{MODULE}.get_entry", return_value=entry),
        patch(f"{MODULE}.banner_effects_for_entry", return_value=["banner"]),
        patch(f"{MODULE}.banner_effects", return_value=["banner"]),
        patch(f"{MODULE}.reload_chart_buttons", return_value=["reload"]),
    ):
        return button.handle(), writer


class TestPlacement:
    def test_the_button_sits_in_the_chart_patient_header(self):
        assert (
            AddToWaitlistButton.BUTTON_LOCATION
            == AddToWaitlistButton.ButtonLocation.CHART_PATIENT_HEADER
        )

    def test_the_button_has_a_stable_key(self):
        # The key identifies the click; changing it orphans the handler.
        assert AddToWaitlistButton.BUTTON_KEY == "scheduling_waitlist__add"


class TestTheLabelFitsTheHeader:
    """A chart header truncates at roughly twelve characters.

    "Add to waitlist" was rendering as "Add to wai…" long before anyone noticed,
    and beside a second button it became impossible to tell the two apart. These
    pin the length, because a label nobody can read is not a label.
    """

    def test_both_labels_are_short_enough_to_render_whole(self):
        from scheduling_waitlist.constants import (
            BUTTON_ADD_TITLE,
            BUTTON_LISTED_TITLE,
        )

        assert len(BUTTON_ADD_TITLE) <= 12
        assert len(BUTTON_LISTED_TITLE) <= 12

    def test_the_two_labels_differ_from_their_first_character(self):
        # Truncation takes the tail, so two labels that share a prefix are one
        # label as far as a reader is concerned.
        from scheduling_waitlist.constants import (
            BUTTON_ADD_TITLE,
            BUTTON_LISTED_TITLE,
        )

        assert BUTTON_ADD_TITLE[0] != BUTTON_LISTED_TITLE[0]

    def test_the_note_button_speaks_the_same_vocabulary(self):
        # Two surfaces, two amounts of information, one pair of words.
        from scheduling_waitlist.handlers.appointment_button import (
            AddToWaitlistAppointmentButton,
        )

        assert (
            AddToWaitlistAppointmentButton.BUTTON_TITLE
            == AddToWaitlistButton.BUTTON_TITLE
        )


class TestVisibility:
    def test_hidden_when_there_is_no_patient(self):
        assert _visible(_button(patient_id=None)) is False

    def test_hidden_when_the_patient_cannot_be_resolved(self):
        # A control that would only fail on click is worse than no control.
        assert _visible(_button(), patient=_patient_model(found=False)) is False

    def test_shown_for_a_patient_not_yet_waiting(self):
        assert _visible(_button(), listed=False) is True

    def test_shown_for_a_patient_already_waiting(self):
        # Still drawn: it becomes the way to the roster.
        assert _visible(_button(), listed=True) is True

    def test_offers_to_add_a_patient_who_is_not_waiting(self):
        button = _button()
        _visible(button, listed=False)

        assert button.BUTTON_TITLE == "Waitlist"

    def test_says_the_patient_is_already_waiting(self):
        button = _button()
        _visible(button, listed=True)

        assert button.BUTTON_TITLE == "On waitlist"

    def test_the_listed_state_is_coloured(self):
        # Reviewers read the listed label as an action because it was drawn like
        # one. Filling it makes the status form look like a state.
        button = _button()
        _visible(button, listed=True)

        assert button.BUTTON_BACKGROUND_COLOR == "#0b7285"
        assert button.BUTTON_TEXT_COLOR == "#ffffff"

    def test_the_action_state_keeps_the_platforms_own_styling(self):
        # So the filled one reads as the exception it is.
        button = _button()
        _visible(button, listed=False)

        assert button.BUTTON_BACKGROUND_COLOR is None
        assert button.BUTTON_TEXT_COLOR is None

    def test_per_render_state_does_not_leak_to_another_patient(self):
        # Assigning either to the class would carry one patient's label and
        # colour onto the next patient's chart.
        _visible(_button(patient_id="listed"), listed=True)

        assert AddToWaitlistButton.BUTTON_TITLE == "Waitlist"
        assert AddToWaitlistButton.BUTTON_BACKGROUND_COLOR is None

    def test_the_live_entry_check_is_keyed_on_the_patients_row_id(self):
        button = _button()
        with (
            patch(f"{MODULE}.Patient", _patient_model(dbid=77)),
            patch(f"{MODULE}.has_live_entry", return_value=False) as lookup,
        ):
            button.visible()

        lookup.assert_called_once_with(77)


class TestClickingToAdd:
    def test_it_writes_the_entry(self):
        _, writer = _click(_button(), listed=False)

        assert writer.call_count == 1

    def test_no_modal_is_opened(self):
        # The whole point: the click is the submission.
        effects, _ = _click(_button(), listed=False)

        assert effects == ["banner", "reload"]

    def test_the_entry_is_attributed_to_the_person_who_clicked(self):
        # Not to nobody: an entry with no creator can be edited or removed only
        # by a configured manager, never by the scheduler who added it.
        _, writer = _click(_button(), listed=False, staff=MagicMock(dbid=101))

        assert writer.call_args.kwargs["created_by_dbid"] == 101

    def test_it_names_the_charts_patient(self):
        _, writer = _click(_button(patient_id="abc-123"), listed=False)

        assert writer.call_args.args[0] == "abc-123"


class TestClickingWhenAlreadyListed:
    def test_it_opens_the_roster(self):
        # Editing, marking scheduled and removing all live there.
        effects, _ = _click(_button(), listed=True)

        assert len(effects) == 1
        assert effects[0].url.startswith("/plugin-io/api/scheduling_waitlist/app/?")

    def test_nothing_is_written(self):
        # The duplicate guard would refuse it, and a scheduler who wants a
        # second differently-specified entry is doing something deliberate.
        _, writer = _click(_button(), listed=True)

        assert writer.call_count == 0

    def test_the_roster_is_not_narrowed_to_one_patient(self):
        # It is the practice-wide list; a patient-scoped roster was reverted.
        effects, _ = _click(_button(), listed=True)

        assert "patient=" not in effects[0].url


class TestWhenTheClickCannotBeAttributed:
    def test_it_opens_the_form_instead(self):
        # The form arrives on an authenticated request, so it attributes
        # correctly. One click slower, and never wrong.
        effects, _ = _click(_button(), listed=False, staff=None)

        assert len(effects) == 1
        assert "/app/add?" in effects[0].url

    def test_nothing_is_written(self):
        _, writer = _click(_button(), listed=False, staff=None)

        assert writer.call_count == 0

    def test_the_form_is_opened_for_the_right_patient(self):
        effects, _ = _click(_button(patient_id="abc-123"), listed=False, staff=None)

        assert "patient=abc-123" in effects[0].url

    def test_a_patient_key_needing_encoding_is_escaped(self):
        effects, _ = _click(_button(patient_id="a b/c"), listed=False, staff=None)

        assert "a b/c" not in effects[0].url
        assert "a%20b%2Fc" in effects[0].url


class TestWhenSomethingElseGotThereFirst:
    def test_a_duplicate_refreshes_the_chart_rather_than_failing(self):
        # The list is already in the state the click asked for.
        effects, _ = _click(_button(), listed=False, error=DuplicateEntryError)

        assert effects[0] == "banner"

    def test_a_duplicate_asks_the_chart_header_to_redraw(self):
        effects, _ = _click(_button(), listed=False, error=DuplicateEntryError)

        assert effects[-1].id == "patient-uuid"

    def test_a_refusal_falls_back_to_the_form(self):
        # The broadest possible request being refused is a fault, and the form
        # is what can show a person the reason.
        effects, _ = _click(
            _button(), listed=False, error=QuickAddRefused({"priority": "no such band"})
        )

        assert "/app/add?" in effects[0].url


class TestGuards:
    def test_a_click_with_no_patient_does_nothing(self):
        effects, writer = _click(_button(patient_id=None))

        assert effects == []
        assert writer.call_count == 0

    def test_a_click_for_an_unresolvable_patient_does_nothing(self):
        effects, writer = _click(_button(), patient=_patient_model(found=False))

        assert effects == []
        assert writer.call_count == 0
