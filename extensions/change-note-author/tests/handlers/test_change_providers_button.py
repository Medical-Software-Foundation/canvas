"""Unit tests for the note-header dropdown button.

Canvas SDK data models, the template renderer, and the modal effect are all
mocked, so these tests run without a live instance.
"""

from unittest.mock import MagicMock, patch

import pytest

from change_note_author.handlers.change_providers_button import ChangeProvidersButton

BUTTON_PATH = "change_note_author.handlers.change_providers_button"
NOTE_DBID = 42


def _button(note_dbid=NOTE_DBID, secrets=None):
    event = MagicMock()
    event.context = {"note_id": note_dbid} if note_dbid is not None else {}
    return ChangeProvidersButton(event, secrets or {})


def _note(note_type_name="Chart Review", provider_id="staff-1", note_id="note-uuid"):
    note = MagicMock()
    note.id = note_id
    note.note_type_version.name = note_type_name
    note.provider.id = provider_id
    return note


def _staff(staff_id, credentialed_name, role="Physician"):
    staff = MagicMock()
    staff.id = staff_id
    staff.credentialed_name = credentialed_name
    staff.top_clinical_role.name = role
    return staff


def _set_note(mock_note, note):
    """Wire up the Note.objects.filter(...).select_related(...).first() chain."""
    mock_note.objects.filter.return_value.select_related.return_value.first.return_value = note


def _set_staff(mock_staff, staff_list):
    """Wire up the Staff.objects.filter(...).prefetch_related(...) chain."""
    mock_staff.objects.filter.return_value.prefetch_related.return_value = staff_list


# ---- button metadata -----------------------------------------------------------

def test_button_is_configured_for_the_note_header_dropdown():
    assert ChangeProvidersButton.BUTTON_TITLE == "Change providers"
    assert ChangeProvidersButton.BUTTON_KEY == "change_note_author"
    assert (
        ChangeProvidersButton.BUTTON_LOCATION
        == ChangeProvidersButton.ButtonLocation.NOTE_HEADER_DROPDOWN
    )


# ---- visible() -----------------------------------------------------------------

def test_hidden_when_event_has_no_note_id():
    button = _button(note_dbid=None)

    with patch(f"{BUTTON_PATH}.Note") as mock_note:
        assert button.visible() is False
        mock_note.objects.filter.assert_not_called()


def test_hidden_when_note_is_not_found():
    button = _button()

    with patch(f"{BUTTON_PATH}.Note") as mock_note:
        _set_note(mock_note, None)

        assert button.visible() is False
        mock_note.objects.filter.assert_called_once_with(dbid=NOTE_DBID)
        mock_note.objects.filter.return_value.select_related.assert_called_once_with(
            "note_type_version"
        )


def test_visible_on_a_chart_review_note():
    button = _button()

    with patch(f"{BUTTON_PATH}.Note") as mock_note:
        _set_note(mock_note, _note("Chart Review"))

        assert button.visible() is True


def test_hidden_on_other_note_types():
    button = _button()

    with patch(f"{BUTTON_PATH}.Note") as mock_note:
        _set_note(mock_note, _note("Office Visit"))

        assert button.visible() is False


def test_visible_uses_the_configured_note_type_name():
    button = _button(secrets={"CHART_REVIEW_NOTE_TYPE_NAME": "Records Review"})

    with patch(f"{BUTTON_PATH}.Note") as mock_note:
        _set_note(mock_note, _note("Records Review"))

        assert button.visible() is True


def test_configured_name_overrides_the_default():
    button = _button(secrets={"CHART_REVIEW_NOTE_TYPE_NAME": "Records Review"})

    with patch(f"{BUTTON_PATH}.Note") as mock_note:
        _set_note(mock_note, _note("Chart Review"))

        assert button.visible() is False


# ---- handle() ------------------------------------------------------------------

def test_handle_returns_nothing_when_the_note_is_gone():
    button = _button()

    with (
        patch(f"{BUTTON_PATH}.Note") as mock_note,
        patch(f"{BUTTON_PATH}.render_to_string") as mock_render,
    ):
        _set_note(mock_note, None)

        assert button.handle() == []
        mock_render.assert_not_called()


@pytest.fixture
def rendered_context():
    """Run handle() against a fixed staff list and capture the template context."""
    button = _button()
    staff_list = [
        _staff("staff-2", "Zoe Adams NP", role="Nurse Practitioner"),
        _staff("staff-1", "Alex Chen MD"),
    ]
    note = _note()
    # The note's author is the same Staff record the picker will list.
    note.provider = staff_list[1]

    with (
        patch(f"{BUTTON_PATH}.Note") as mock_note,
        patch(f"{BUTTON_PATH}.Staff") as mock_staff,
        patch(f"{BUTTON_PATH}.render_to_string") as mock_render,
        patch(f"{BUTTON_PATH}.LaunchModalEffect") as mock_modal,
    ):
        _set_note(mock_note, note)
        _set_staff(mock_staff, staff_list)
        mock_render.return_value = "<html></html>"

        effects = button.handle()

        mock_staff.objects.filter.assert_called_once_with(active=True)
        mock_staff.objects.filter.return_value.prefetch_related.assert_called_once_with(
            "roles"
        )
        template, context = mock_render.call_args.args
        yield {
            "effects": effects,
            "template": template,
            "context": context,
            "modal": mock_modal,
        }


def test_handle_renders_the_modal_template(rendered_context):
    assert rendered_context["template"] == "templates/change_provider.html"


def test_handle_launches_a_centered_modal(rendered_context):
    modal = rendered_context["modal"]
    modal.assert_called_once_with(
        content="<html></html>",
        target=modal.TargetType.DEFAULT_MODAL,
        title="Change providers",
    )
    assert rendered_context["effects"] == [modal.return_value.apply.return_value]


def test_handle_passes_the_current_author(rendered_context):
    context = rendered_context["context"]
    assert context["note_id"] == "note-uuid"
    assert context["current_provider_name"] == "Alex Chen MD"
    assert context["current_provider_initials"] == "AC"
    assert context["current_provider_id"] == "staff-1"


def test_handle_sorts_staff_by_name_and_flags_the_current_author(rendered_context):
    options = rendered_context["context"]["staff_options"]

    assert [option["name"] for option in options] == ["Alex Chen MD", "Zoe Adams NP"]
    assert options[0]["is_current"] is True
    assert options[1]["is_current"] is False
    assert options[1]["subtitle"] == "Nurse Practitioner"
    assert options[1]["search"] == "zoe adams np nurse practitioner"


def test_handle_labels_an_unassigned_note():
    button = _button()
    note = _note()
    note.provider = None

    with (
        patch(f"{BUTTON_PATH}.Note") as mock_note,
        patch(f"{BUTTON_PATH}.Staff") as mock_staff,
        patch(f"{BUTTON_PATH}.render_to_string") as mock_render,
        patch(f"{BUTTON_PATH}.LaunchModalEffect"),
    ):
        _set_note(mock_note, note)
        _set_staff(mock_staff, [])

        button.handle()

        _, context = mock_render.call_args.args

    assert context["current_provider_name"] == "Unassigned"
    assert context["current_provider_id"] == ""
    assert context["staff_options"] == []
