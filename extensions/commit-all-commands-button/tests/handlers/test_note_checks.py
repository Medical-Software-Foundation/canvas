from unittest.mock import Mock, patch

import pytest

from canvas_sdk.commands import HistoryOfPresentIllnessCommand, POCLabTestCommand
from canvas_sdk.v1.data.note import NoteStates, NoteTypeCategories

from canvas_sdk.commands import FollowUpCommand, UpdateDiagnosisCommand

from commit_all_commands_button.handlers.commit_all_commands import (
    CommitButtonHandler,
    command_label,
    field_label,
    is_blank,
    missing_fields_reason,
    normalize_uuid,
)

MODULE = "commit_all_commands_button.handlers.commit_all_commands"


def make_note(category: str = NoteTypeCategories.ENCOUNTER, body: list | None = None) -> Mock:
    note = Mock()
    note.dbid = 42
    note.note_type_version.category = category
    note.body = body
    return note


class TestAcceptsCommits:
    """Whether the note accepts commits, matching Canvas's own note check."""

    @pytest.mark.parametrize(
        "state", [NoteStates.NEW, NoteStates.UNLOCKED, NoteStates.RESTORED, NoteStates.UNDELETED]
    )
    @patch(f"{MODULE}.CurrentNoteStateEvent")
    def test_open_states_accept_commits(self, mock_state_model, state):
        mock_state_model.objects.filter.return_value.first.return_value = Mock(state=state)

        assert CommitButtonHandler.accepts_commits(make_note()) is True
        mock_state_model.objects.filter.assert_called_once_with(note__dbid=42)

    @pytest.mark.parametrize("state", [NoteStates.LOCKED, NoteStates.RELOCKED, NoteStates.SIGNED])
    @patch(f"{MODULE}.CurrentNoteStateEvent")
    def test_locked_and_signed_states_reject_commits(self, mock_state_model, state):
        mock_state_model.objects.filter.return_value.first.return_value = Mock(state=state)

        assert CommitButtonHandler.accepts_commits(make_note()) is False

    @pytest.mark.parametrize("state", [NoteStates.LOCKED, NoteStates.RELOCKED, NoteStates.SIGNED])
    @patch(f"{MODULE}.CurrentNoteStateEvent")
    def test_locked_data_notes_accept_commits(self, mock_state_model, state):
        mock_state_model.objects.filter.return_value.first.return_value = Mock(state=state)

        assert CommitButtonHandler.accepts_commits(make_note(NoteTypeCategories.DATA)) is True

    @pytest.mark.parametrize("state", [NoteStates.DELETED, NoteStates.CANCELLED])
    @pytest.mark.parametrize("category", [NoteTypeCategories.ENCOUNTER, NoteTypeCategories.DATA])
    @patch(f"{MODULE}.CurrentNoteStateEvent")
    def test_deleted_and_canceled_states_reject_commits(self, mock_state_model, state, category):
        mock_state_model.objects.filter.return_value.first.return_value = Mock(state=state)

        assert CommitButtonHandler.accepts_commits(make_note(category)) is False

    @patch(f"{MODULE}.CurrentNoteStateEvent")
    def test_note_without_state_accepts_commits(self, mock_state_model):
        mock_state_model.objects.filter.return_value.first.return_value = None

        assert CommitButtonHandler.accepts_commits(make_note()) is True


class TestCommandUuidsInBody:
    """The command UUIDs read from the note body."""

    def test_reads_command_uuids_from_both_note_body_versions(self):
        body = [
            {"type": "text", "value": "Patient reports headache"},
            # Version 1 note: the stored node carries the command's dbid and UUID.
            {"type": "command", "value": "hpi", "data": {"id": 7, "command_uuid": "AAAA-bbbb"}},
            # Version 2 note: the SDK rebuilds each command line with its UUID only.
            {"type": "command", "value": "plan", "data": {"command_uuid": "cccc-dddd"}},
        ]

        assert CommitButtonHandler.command_uuids_in_body(make_note(body=body)) == {
            "aaaabbbb",
            "ccccdddd",
        }

    def test_ignores_command_lines_without_a_uuid(self):
        body = [
            {"type": "command", "value": "hpi", "data": {"id": 7}},
            {"type": "command", "value": "plan"},
            {"type": "command", "value": "plan", "data": None},
        ]

        assert CommitButtonHandler.command_uuids_in_body(make_note(body=body)) == set()

    def test_empty_body(self):
        assert CommitButtonHandler.command_uuids_in_body(make_note(body=None)) == set()


class TestHelpers:
    @pytest.mark.parametrize("value", [None, "", "  \n\t", [], {}])
    def test_blank_values(self, value):
        assert is_blank(value) is True

    @pytest.mark.parametrize("value", ["x", {"value": 1}, [1], 0, False, "null"])
    def test_non_blank_values(self, value):
        assert is_blank(value) is False

    def test_normalize_uuid_matches_dashed_and_undashed(self):
        dashed = "066F3266-49E8-421A-9476-D1BE1C97E00C"
        assert normalize_uuid(dashed) == normalize_uuid("066f326649e8421a9476d1be1c97e00c")

    def test_field_labels(self):
        assert field_label(FollowUpCommand.Meta.key, "note_type") == "Visit Type"
        assert field_label(UpdateDiagnosisCommand.Meta.key, "new_condition") == "New Diagnosis"
        assert field_label(POCLabTestCommand.Meta.key, "template") == "POC Lab Test"
        assert field_label(FollowUpCommand.Meta.key, "requested_date") == "Requested date"
        assert field_label(HistoryOfPresentIllnessCommand.Meta.key, "narrative") == "Narrative"

    def test_missing_fields_reason(self):
        assert missing_fields_reason(["Narrative"]) == "Empty required field: Narrative"
        assert missing_fields_reason(["Title", "Assign to"]) == "Empty required fields: Title, Assign to"

    def test_command_labels(self):
        assert command_label(HistoryOfPresentIllnessCommand) == "History Of Present Illness"
        assert command_label(POCLabTestCommand) == "POC Lab Test"


class TestSkippedCommandsTemplate:
    """The skipped-commands template rendered with the SDK's template engine."""

    @staticmethod
    def render(context: dict) -> str:
        from pathlib import Path

        from canvas_sdk.templates.utils import _engine_for_plugin

        plugin_dir = Path(__file__).resolve().parents[2] / "commit_all_commands_button"
        return _engine_for_plugin(str(plugin_dir)).render_to_string(
            str(plugin_dir / "templates" / "skipped_commands.html"), context=context
        )

    def test_lists_skipped_commands_escaped(self):
        html = self.render(
            {
                "skipped": [
                    {"label": "History Of Present Illness", "reason": "Empty required field: Narrative"},
                    {"label": "<b>Plan</b>", "reason": "Saved to this note but not shown in it"},
                ]
            }
        )

        assert "<td>History Of Present Illness</td><td>Empty required field: Narrative</td>" in html
        assert "&lt;b&gt;Plan&lt;/b&gt;" in html

    def test_go_to_note_button_closes_the_modal(self):
        html = self.render({"skipped": [{"label": "Plan", "reason": "x"}]})

        assert '<button type="button" onclick="closeModal()">Go to note</button>' in html
        assert 'event.data.type === "INIT_CHANNEL"' in html
        assert 'messagePort.postMessage({ type: "CLOSE_MODAL" })' in html
