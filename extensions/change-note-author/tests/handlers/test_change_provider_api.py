"""Unit tests for the change-provider HTTP route.

Every Canvas SDK dependency (data models, the Note effect) is mocked, so these
tests never touch a database or a live instance.
"""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest

from change_note_author.handlers.change_provider_api import ChangeProviderAPI

NOTE_ID = "note-1"
PROVIDER_ID = "staff-new"
CURRENT_PROVIDER_ID = "staff-current"
ACTING_STAFF_ID = "staff-actor"


@pytest.fixture
def route():
    """A ChangeProviderAPI instance with a mocked request and staff session."""
    api = ChangeProviderAPI(MagicMock())
    api.request = MagicMock()
    api.request.headers.get.return_value = ACTING_STAFF_ID
    return api


def _body(response):
    return json.loads(response.content)


def _note(provider_id=CURRENT_PROVIDER_ID, editable=True, note_type_name="Chart Review"):
    note = MagicMock()
    note.provider.id = provider_id
    note.note_type_version.name = note_type_name
    note.current_state.editable.return_value = editable
    return note


def _staff(active=True):
    staff = MagicMock()
    staff.active = active
    return staff


def _set_note(mock_note, note):
    """Wire up the Note.objects.filter(...).select_related(...).first() chain."""
    mock_note.objects.filter.return_value.select_related.return_value.first.return_value = note


def _assert_note_query(mock_note):
    mock_note.objects.filter.assert_called_once_with(id=NOTE_ID)
    mock_note.objects.filter.return_value.select_related.assert_called_once_with(
        "note_type_version"
    )


# ---- request body validation ---------------------------------------------------

def test_non_json_body_is_rejected(route):
    route.request.json.side_effect = ValueError("not json")

    responses = route.post()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert _body(responses[0]) == {"ok": False, "error": "Request body must be valid JSON."}
    assert route.request.mock_calls == [call.json()]


def test_non_object_body_is_rejected(route):
    route.request.json.return_value = ["not", "a", "dict"]

    responses = route.post()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert _body(responses[0])["error"] == "Request body must be a JSON object."


def test_missing_note_id_is_rejected(route):
    route.request.json.return_value = {"new_provider_id": PROVIDER_ID}

    responses = route.post()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert _body(responses[0])["error"] == "A note id is required."


def test_missing_provider_id_is_rejected(route):
    route.request.json.return_value = {"note_id": NOTE_ID}

    responses = route.post()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert _body(responses[0])["error"] == "Please choose a provider."


def test_whitespace_only_ids_are_rejected(route):
    route.request.json.return_value = {"note_id": "   ", "new_provider_id": PROVIDER_ID}

    responses = route.post()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert _body(responses[0])["error"] == "A note id is required."


# ---- record lookups ------------------------------------------------------------

def test_unknown_note_returns_not_found(route):
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with patch("change_note_author.handlers.change_provider_api.Note") as mock_note:
        _set_note(mock_note, None)

        responses = route.post()

        _assert_note_query(mock_note)

    assert responses[0].status_code == HTTPStatus.NOT_FOUND
    assert _body(responses[0])["error"] == "That note could not be found."


def test_unknown_provider_is_rejected(route):
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
    ):
        _set_note(mock_note, _note())
        mock_staff.objects.filter.return_value.first.return_value = None

        responses = route.post()

        mock_staff.objects.filter.assert_called_once_with(id=PROVIDER_ID)

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert _body(responses[0])["error"] == "The selected provider could not be found."


def test_inactive_provider_is_rejected(route):
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
    ):
        _set_note(mock_note, _note())
        mock_staff.objects.filter.return_value.first.return_value = _staff(active=False)

        responses = route.post()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert (
        _body(responses[0])["error"]
        == "The selected provider is not active and cannot be assigned."
    )


# ---- note type is enforced server-side -----------------------------------------

def test_other_note_types_are_refused(route):
    """The dropdown is hidden elsewhere, but the route must enforce it too."""
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, _note(note_type_name="Office Visit"))

        responses = route.post()

        # Rejected before any provider lookup or write is attempted.
        mock_staff.objects.filter.assert_not_called()
        mock_effect.assert_not_called()

    assert responses[0].status_code == HTTPStatus.FORBIDDEN
    assert (
        _body(responses[0])["error"]
        == "This plugin can only change the author of Chart Review notes."
    )


def test_note_with_no_type_is_refused(route):
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}
    note = _note()
    note.note_type_version = None

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, note)

        responses = route.post()

        mock_effect.assert_not_called()

    assert responses[0].status_code == HTTPStatus.FORBIDDEN


def test_route_honours_the_configured_note_type_name(route):
    route.secrets = {"CHART_REVIEW_NOTE_TYPE_NAME": "Records Review"}
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, _note(note_type_name="Records Review"))
        mock_staff.objects.filter.return_value.first.return_value = _staff()

        responses = route.post()

        mock_effect.assert_called_once_with(instance_id=NOTE_ID)

    assert len(responses) == 2


def test_configured_name_makes_the_default_unacceptable(route):
    route.secrets = {"CHART_REVIEW_NOTE_TYPE_NAME": "Records Review"}
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with patch("change_note_author.handlers.change_provider_api.Note") as mock_note:
        _set_note(mock_note, _note(note_type_name="Chart Review"))

        responses = route.post()

    assert responses[0].status_code == HTTPStatus.FORBIDDEN


# ---- no-op and locked notes ----------------------------------------------------

def test_reassigning_to_the_same_provider_is_a_noop(route):
    route.request.json.return_value = {
        "note_id": NOTE_ID,
        "new_provider_id": CURRENT_PROVIDER_ID,
    }

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, _note())
        mock_staff.objects.filter.return_value.first.return_value = _staff()

        responses = route.post()

        mock_effect.assert_not_called()

    assert len(responses) == 1
    assert _body(responses[0]) == {
        "ok": True,
        "noop": True,
        "message": "That provider is already the author of this note.",
    }


def test_locked_note_is_rejected(route):
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, _note(editable=False))
        mock_staff.objects.filter.return_value.first.return_value = _staff()

        responses = route.post()

        mock_effect.assert_not_called()

    assert responses[0].status_code == HTTPStatus.CONFLICT
    assert (
        _body(responses[0])["error"]
        == "This note is locked or finalized, so its author cannot be changed."
    )


def test_note_with_no_state_is_treated_as_editable(route):
    """A note whose state we cannot read should not be blocked client-side."""
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}
    note = _note()
    note.current_state = None

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, note)
        mock_staff.objects.filter.return_value.first.return_value = _staff()

        responses = route.post()

        mock_effect.assert_called_once_with(instance_id=NOTE_ID)

    assert len(responses) == 2


# ---- the happy path ------------------------------------------------------------

def test_successful_reassignment_returns_effect_and_confirmation(route):
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, _note())
        mock_staff.objects.filter.return_value.first.return_value = _staff()
        effect_instance = mock_effect.return_value

        responses = route.post()

        mock_effect.assert_called_once_with(instance_id=NOTE_ID)
        assert effect_instance.provider_id == PROVIDER_ID
        effect_instance.update.assert_called_once_with()

    assert len(responses) == 2
    assert responses[0] is effect_instance.update.return_value
    assert _body(responses[1]) == {
        "ok": True,
        "message": "The note's author has been updated.",
    }


def test_successful_reassignment_logs_the_acting_staff_member(route):
    """The audit line must record who made the change, not just who received it."""
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect"),
        patch("change_note_author.handlers.change_provider_api.log") as mock_log,
    ):
        _set_note(mock_note, _note())
        mock_staff.objects.filter.return_value.first.return_value = _staff()

        route.post()

        route.request.headers.get.assert_called_once_with("canvas-logged-in-user-id")
        mock_log.info.assert_called_once()
        message = mock_log.info.call_args.args[0]

    assert ACTING_STAFF_ID in message
    assert NOTE_ID in message
    assert PROVIDER_ID in message


def test_acting_staff_falls_back_when_the_header_is_absent(route):
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}
    route.request.headers.get.return_value = None

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect"),
        patch("change_note_author.handlers.change_provider_api.log") as mock_log,
    ):
        _set_note(mock_note, _note())
        mock_staff.objects.filter.return_value.first.return_value = _staff()

        route.post()

        message = mock_log.info.call_args.args[0]

    assert "unknown" in message


def test_note_with_no_current_provider_can_be_assigned(route):
    """An unassigned note has no provider id to compare against."""
    route.request.json.return_value = {"note_id": NOTE_ID, "new_provider_id": PROVIDER_ID}
    note = _note()
    note.provider = None

    with (
        patch("change_note_author.handlers.change_provider_api.Note") as mock_note,
        patch("change_note_author.handlers.change_provider_api.Staff") as mock_staff,
        patch("change_note_author.handlers.change_provider_api.NoteEffect") as mock_effect,
    ):
        _set_note(mock_note, note)
        mock_staff.objects.filter.return_value.first.return_value = _staff()

        responses = route.post()

        mock_effect.assert_called_once_with(instance_id=NOTE_ID)

    assert len(responses) == 2
    assert _body(responses[1])["ok"] is True
