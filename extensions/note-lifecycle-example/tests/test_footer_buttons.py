import json
from unittest.mock import MagicMock, patch

import pytest

from note_lifecycle_example.handlers import footer_buttons
from note_lifecycle_example.handlers.footer_buttons import (
    CancelAppointmentButton,
    CheckInAppointmentButton,
    DeleteNoteButton,
    DischargeNoteButton,
    LockNoteButton,
    NoShowAppointmentButton,
    PushChargesNoteButton,
    RestoreAppointmentButton,
    RestoreNoteButton,
    SignNoteButton,
    UnlockNoteButton,
)

from canvas_sdk.handlers.action_button import ActionButton, NoteStateActionButton
from canvas_sdk.test_utils.factories import NoteFactory
from canvas_sdk.v1.data.note import NoteStates, NoteTypeCategories

# Each footer button mapped to the state its click transitions the note into. Titles aren't
# pinned here since buttons may set a custom BUTTON_TITLE (default derivation is covered by the
# SDK's own tests).
BUTTONS: dict[type[NoteStateActionButton], NoteStates] = {
    LockNoteButton: NoteStates.LOCKED,
    SignNoteButton: NoteStates.SIGNED,
    UnlockNoteButton: NoteStates.UNLOCKED,
    PushChargesNoteButton: NoteStates.PUSHED,
    CheckInAppointmentButton: NoteStates.CONVERTED,
    NoShowAppointmentButton: NoteStates.NOSHOW,
    DeleteNoteButton: NoteStates.DELETED,
    RestoreNoteButton: NoteStates.UNDELETED,
    DischargeNoteButton: NoteStates.DISCHARGED,
    CancelAppointmentButton: NoteStates.CANCELLED,
    RestoreAppointmentButton: NoteStates.REVERTED,
}


def _button(
    cls: type[NoteStateActionButton], note_id: int = 1
) -> NoteStateActionButton:
    """Build a button instance whose event context carries the given note id."""
    event = MagicMock()
    event.context = {"note_id": note_id}
    return cls(event=event)


def test_buttons_subclass_note_state_action_button() -> None:
    """Each footer button is a NoteStateActionButton in the note footer."""
    for cls in BUTTONS:
        assert issubclass(cls, NoteStateActionButton)
        assert cls.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_FOOTER


def test_buttons_target_expected_states() -> None:
    """Each button transitions the note into its expected state."""
    for cls, state in BUTTONS.items():
        assert state == cls.STATE_ACTION


def test_buttons_have_titles_and_unique_keys() -> None:
    """Every button exposes a non-empty title and a key unique across the footer."""
    for cls in BUTTONS:
        assert cls.BUTTON_TITLE
    keys = [cls.BUTTON_KEY for cls in BUTTONS]
    assert len(set(keys)) == len(keys)


@patch.object(
    NoteStateActionButton,
    "_note_context",
    return_value=(NoteStates.NEW, False, NoteTypeCategories.INPATIENT),
)
def test_discharge_only_for_inpatient_note_types(_mock_state: MagicMock) -> None:
    """Discharge shows for inpatient note types but not for encounters."""
    with patch.object(
        footer_buttons,
        "_note_type_info",
        return_value=(NoteTypeCategories.INPATIENT, True),
    ):
        assert _button(DischargeNoteButton).visible() is True

    with patch.object(
        footer_buttons,
        "_note_type_info",
        return_value=(NoteTypeCategories.ENCOUNTER, True),
    ):
        assert _button(DischargeNoteButton).visible() is False


@patch.object(
    NoteStateActionButton,
    "_note_context",
    return_value=(NoteStates.NEW, False, NoteTypeCategories.INPATIENT),
)
def test_discharge_hidden_without_a_note(_mock_state: MagicMock) -> None:
    """Discharge stays hidden when the context carries no note."""
    with patch.object(footer_buttons, "_note_type_info", return_value=None):
        assert _button(DischargeNoteButton).visible() is False


def test_colored_buttons_use_the_green_palette() -> None:
    """Any button that sets a background uses the plugin's green-on-white palette."""
    colored = [cls for cls in BUTTONS if cls.BUTTON_BACKGROUND_COLOR is not None]
    assert colored  # at least one button is styled
    for cls in colored:
        assert cls.BUTTON_BACKGROUND_COLOR == footer_buttons._GREEN
        assert cls.BUTTON_TEXT_COLOR == footer_buttons._WHITE


@patch.object(
    NoteStateActionButton,
    "_note_context",
    return_value=(NoteStates.LOCKED, False, NoteTypeCategories.ENCOUNTER),
)
def test_unlock_title_overridden_for_signature_required(_mock_state: MagicMock) -> None:
    """Unlock keeps its default title for non-sig notes and overrides it for sig-required ones."""
    event = MagicMock()
    event.name = "SHOW_NOTE_FOOTER_BUTTON"
    event.context = {"note_id": 1}

    def title(is_sig_required: bool) -> str:
        with patch.object(
            footer_buttons,
            "_note_type_info",
            return_value=(NoteTypeCategories.ENCOUNTER, is_sig_required),
        ):
            effects = UnlockNoteButton(event=event).compute()
        return str(json.loads(effects[0].payload)["data"]["title"])

    assert title(is_sig_required=False) == UnlockNoteButton.BUTTON_TITLE
    assert title(is_sig_required=True) != title(is_sig_required=False)


def test_sign_hidden_while_note_has_uncommitted_commands() -> None:
    """Sign is hidden while staged commands remain, even when the transition is allowed.

    Reason-for-visit is auto-managed and must not block signing, so it is excluded from the
    staged-command check.
    """
    with (
        patch.object(NoteStateActionButton, "visible", return_value=True),
        patch.object(footer_buttons.Command, "objects") as objects,
    ):
        staged = objects.filter.return_value.exclude.return_value

        staged.exists.return_value = True
        assert _button(SignNoteButton).visible() is False

        staged.exists.return_value = False
        assert _button(SignNoteButton).visible() is True

    objects.filter.assert_called_with(note_id=1, state="staged")
    objects.filter.return_value.exclude.assert_called_with(schema_key="reasonForVisit")


def test_sign_hidden_when_transition_disallowed_without_checking_commands() -> None:
    """When the base transition isn't allowed, Sign stays hidden and never queries commands."""
    with (
        patch.object(NoteStateActionButton, "visible", return_value=False),
        patch.object(footer_buttons.Command, "objects") as objects,
    ):
        assert _button(SignNoteButton).visible() is False
        objects.filter.assert_not_called()


@pytest.mark.django_db
def test_note_type_info_reads_category_and_sig_required_from_db() -> None:
    """_note_type_info pulls the note's (category, is_sig_required) straight from the DB.

    Every other test mocks this helper, so this is the one case that exercises the real
    Note -> note_type_version lookup against the test database with factories.
    """
    note = NoteFactory.create(
        note_type_version__category=NoteTypeCategories.INPATIENT,
        note_type_version__is_sig_required=True,
    )

    assert footer_buttons._note_type_info(note.dbid) == (
        NoteTypeCategories.INPATIENT,
        True,
    )


@pytest.mark.django_db
def test_note_type_info_returns_none_without_a_matching_note() -> None:
    """A falsy id short-circuits, and an id with no note yields None from the query."""
    assert footer_buttons._note_type_info(None) is None
    assert footer_buttons._note_type_info(0) is None
    assert footer_buttons._note_type_info(999_999_999) is None
