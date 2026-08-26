"""The chart button that adds a patient to the waitlist in one click.

Its sibling in ``chart_button.py`` opens a form whose every field already defaults
to the broadest setting, so the common request was costing a modal load and a
second click to accept answers that were already right. This button is that click.
"""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.quick_add_button import (
    QUICK_TITLE,
    QuickAddToWaitlistButton,
)
from scheduling_waitlist.services.entries import DuplicateEntryError
from scheduling_waitlist.services.quick_add import QuickAddRefused

MODULE = "scheduling_waitlist.handlers.quick_add_button"

# Distinguishes "the test did not care" from "the test means None". Passing None
# for the staff member is the interesting case, so it cannot also be the default.
UNSET = object()


def _button(patient_id="patient-uuid", actor_id=7):
    button = QuickAddToWaitlistButton.__new__(QuickAddToWaitlistButton)
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
    """A patient model that resolves the very patient the event names.

    Built from the event rather than fixed, so a test that changes the chart's
    patient sees that patient reach the writer.
    """
    return _patient_model(patient_id=button.event.target.id)


def _visible(button, listed=False, patient=None):
    with (
        patch(f"{MODULE}.Patient", patient or _for_button(button)),
        patch(f"{MODULE}.has_live_general_entry", return_value=listed),
    ):
        return button.visible()


def _handle(
    button,
    *,
    staff=UNSET,
    quick_add_result=None,
    quick_add_error=None,
    patient=None,
):
    """Run the click with every collaborator stubbed, returning the effects."""
    entry = quick_add_result if quick_add_result is not None else MagicMock(dbid=900)
    with (
        patch(f"{MODULE}.Patient", patient or _for_button(button)),
        patch(
            f"{MODULE}.staff_from_actor",
            return_value=MagicMock(dbid=101) if staff is UNSET else staff,
        ),
        patch(
            f"{MODULE}.quick_add",
            side_effect=quick_add_error,
            return_value=entry,
        ) as writer,
        patch(f"{MODULE}.get_entry", return_value=entry),
        patch(f"{MODULE}.banner_effects_for_entry", return_value=["banner"]),
        patch(f"{MODULE}.banner_effects", return_value=["banner"]),
        patch(f"{MODULE}.reload_chart_buttons", return_value=["reload"]),
    ):
        return button.handle(), writer


class TestPlacement:
    def test_it_sits_in_the_chart_patient_header(self):
        assert (
            QuickAddToWaitlistButton.BUTTON_LOCATION
            == QuickAddToWaitlistButton.ButtonLocation.CHART_PATIENT_HEADER
        )

    def test_it_has_its_own_key(self):
        # A key shared with the form button would send both clicks to one
        # handler and the other button would stop working.
        assert QuickAddToWaitlistButton.BUTTON_KEY == "scheduling_waitlist__quick_add"

    def test_the_key_differs_from_the_form_buttons(self):
        from scheduling_waitlist.handlers.appointment_button import (
            AddToWaitlistAppointmentButton,
        )
        from scheduling_waitlist.handlers.chart_button import AddToWaitlistButton

        keys = {
            QuickAddToWaitlistButton.BUTTON_KEY,
            AddToWaitlistButton.BUTTON_KEY,
            AddToWaitlistAppointmentButton.BUTTON_KEY,
        }

        assert len(keys) == 3

    def test_its_label_says_the_terms_it_will_use(self):
        assert QuickAddToWaitlistButton.BUTTON_TITLE == QUICK_TITLE


class TestVisibility:
    def test_hidden_when_the_event_names_no_patient(self):
        assert _visible(_button(patient_id=None)) is False

    def test_hidden_when_the_patient_cannot_be_resolved(self):
        assert _visible(_button(), patient=_patient_model(found=False)) is False

    def test_shown_for_a_patient_with_no_general_entry(self):
        assert _visible(_button(), listed=False) is True

    def test_hidden_once_they_already_have_a_general_entry(self):
        # The click writes immediately, so there is no form to carry an "already
        # on the list" message back to. The sibling button still says so.
        assert _visible(_button(), listed=True) is False


class TestTheClick:
    def test_it_writes_the_entry(self):
        _, writer = _handle(_button())

        assert writer.call_count == 1

    def test_the_entry_is_attributed_to_the_person_who_clicked(self):
        # Not to nobody: an entry with no creator can be edited or removed only
        # by a configured manager, never by the scheduler who added it.
        _, writer = _handle(_button(), staff=MagicMock(dbid=101))

        assert writer.call_args.kwargs["created_by_dbid"] == 101

    def test_it_names_the_charts_patient(self):
        _, writer = _handle(_button(patient_id="abc-123"))

        assert writer.call_args.args[0] == "abc-123"

    def test_the_chart_is_brought_up_to_date(self):
        # The banner has to start saying they are waiting, and the sibling
        # button has to stop offering to add them.
        effects, _ = _handle(_button())

        assert effects == ["banner", "reload"]

    def test_no_modal_is_opened(self):
        # The whole point: the click is the submission.
        effects, _ = _handle(_button())

        assert all(effect in ("banner", "reload") for effect in effects)


class TestWhenTheClickCannotBeAttributed:
    def test_it_opens_the_form_instead(self):
        # The form arrives on an authenticated request, so it attributes
        # correctly. One click slower, and never wrong.
        effects, _ = _handle(_button(), staff=None)

        assert len(effects) == 1
        assert "/app/add?" in effects[0].url

    def test_nothing_is_written(self):
        _, writer = _handle(_button(), staff=None)

        assert writer.call_count == 0

    def test_the_form_is_opened_for_the_right_patient(self):
        effects, _ = _handle(_button(patient_id="abc-123"), staff=None)

        assert "patient=abc-123" in effects[0].url


class TestWhenSomethingElseGotThereFirst:
    def test_a_duplicate_refreshes_the_chart_rather_than_failing(self):
        # The list is already in the state the click asked for, so the only
        # thing left is making the chart say so.
        effects, _ = _handle(_button(), quick_add_error=DuplicateEntryError)

        assert effects[0] == "banner"

    def test_a_duplicate_asks_the_chart_header_to_redraw(self):
        effects, _ = _handle(_button(), quick_add_error=DuplicateEntryError)

        assert effects[-1].id == "patient-uuid"

    def test_a_refusal_falls_back_to_the_form(self):
        # The broadest possible request being refused is a fault, and the form
        # is what can show a person the reason.
        effects, _ = _handle(
            _button(), quick_add_error=QuickAddRefused({"priority": "no such band"})
        )

        assert "/app/add?" in effects[0].url


class TestGuards:
    def test_a_click_naming_no_patient_does_nothing(self):
        effects, writer = _handle(_button(patient_id=None))

        assert effects == []
        assert writer.call_count == 0

    def test_a_click_for_an_unresolvable_patient_does_nothing(self):
        effects, writer = _handle(_button(), patient=_patient_model(found=False))

        assert effects == []
        assert writer.call_count == 0
