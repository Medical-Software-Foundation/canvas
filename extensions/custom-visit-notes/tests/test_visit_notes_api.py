import json
from unittest.mock import MagicMock, patch

from custom_visit_notes.handlers.visit_notes_api import VisitNotesAPI


def _make_api(query_params=None, body=None, secrets=None):
    request = MagicMock()
    request.query_params = query_params or {}
    request.json.return_value = body

    handler = VisitNotesAPI.__new__(VisitNotesAPI)
    handler.request = request
    handler.secrets = secrets or {}
    return handler


NOTE_UUID = "eb618d69-52df-4ac0-8ac0-9a457ee15981"
NOTE_DBID = 1425


class TestGetApp:
    def test_missing_note_id_returns_400(self):
        handler = _make_api(query_params={})
        effects = handler.get_app()
        assert len(effects) == 1
        assert effects[0].status_code == 400

    @patch("custom_visit_notes.handlers.visit_notes_api.render_to_string", return_value="<html></html>")
    @patch("custom_visit_notes.handlers.visit_notes_api.VisitNote")
    @patch("custom_visit_notes.handlers.visit_notes_api.Note")
    def test_renders_template_for_valid_note(self, mock_note, mock_visit_note, mock_render):
        mock_note.objects.get.return_value = MagicMock(dbid=NOTE_DBID)
        mock_visit_note.objects.filter.return_value.first.return_value = None

        handler = _make_api(
            query_params={"note_id": NOTE_UUID},
            secrets={"tab_name": "Therapy Notes"},
        )
        effects = handler.get_app()

        assert len(effects) == 1
        assert effects[0].status_code == 200
        mock_render.assert_called_once()
        context = mock_render.call_args[0][1]
        assert context["tab_name"] == "Therapy Notes"
        assert json.loads(context["content"]) == ""

    @patch("custom_visit_notes.handlers.visit_notes_api.render_to_string", return_value="<html></html>")
    @patch("custom_visit_notes.handlers.visit_notes_api.VisitNote")
    @patch("custom_visit_notes.handlers.visit_notes_api.Note")
    def test_renders_existing_content(self, mock_note, mock_visit_note, mock_render):
        mock_note.objects.get.return_value = MagicMock(dbid=NOTE_DBID)
        existing = MagicMock(content="patient discussed anxiety")
        mock_visit_note.objects.filter.return_value.first.return_value = existing

        handler = _make_api(query_params={"note_id": NOTE_UUID})
        effects = handler.get_app()

        context = mock_render.call_args[0][1]
        assert json.loads(context["content"]) == "patient discussed anxiety"

    @patch("custom_visit_notes.handlers.visit_notes_api.Note")
    def test_note_not_found_returns_404(self, mock_note):
        from canvas_sdk.v1.data.note import Note

        mock_note.DoesNotExist = Note.DoesNotExist
        mock_note.objects.get.side_effect = Note.DoesNotExist

        handler = _make_api(query_params={"note_id": NOTE_UUID})
        effects = handler.get_app()
        assert len(effects) == 1
        assert effects[0].status_code == 404


class TestSave:
    def test_missing_note_id_returns_400(self):
        handler = _make_api(query_params={}, body={"content": "hello"})
        effects = handler.save()
        assert len(effects) == 1
        assert effects[0].status_code == 400

    @patch("custom_visit_notes.handlers.visit_notes_api.VisitNote")
    @patch("custom_visit_notes.handlers.visit_notes_api.Note")
    def test_creates_new_visit_note(self, mock_note, mock_visit_note):
        from datetime import datetime, timezone

        mock_note.objects.get.return_value = MagicMock(dbid=NOTE_DBID)
        saved = MagicMock(updated_at=datetime(2026, 5, 26, tzinfo=timezone.utc))
        mock_visit_note.objects.update_or_create.return_value = (saved, True)

        handler = _make_api(
            query_params={"note_id": NOTE_UUID},
            body={"content": "new therapy note"},
        )
        effects = handler.save()

        assert len(effects) == 1
        resp = json.loads(effects[0].content)
        assert resp["status"] == "saved"
        mock_visit_note.objects.update_or_create.assert_called_once_with(
            note_id=NOTE_DBID,
            defaults={"content": "new therapy note"},
        )

    @patch("custom_visit_notes.handlers.visit_notes_api.Note")
    def test_save_note_not_found_returns_404(self, mock_note):
        from canvas_sdk.v1.data.note import Note

        mock_note.DoesNotExist = Note.DoesNotExist
        mock_note.objects.get.side_effect = Note.DoesNotExist

        handler = _make_api(
            query_params={"note_id": NOTE_UUID},
            body={"content": "hello"},
        )
        effects = handler.save()
        assert len(effects) == 1
        assert effects[0].status_code == 404


class TestLoad:
    def test_missing_note_id_returns_400(self):
        handler = _make_api(query_params={})
        effects = handler.load()
        assert len(effects) == 1
        assert effects[0].status_code == 400

    @patch("custom_visit_notes.handlers.visit_notes_api.VisitNote")
    @patch("custom_visit_notes.handlers.visit_notes_api.Note")
    def test_load_empty_note(self, mock_note, mock_visit_note):
        mock_note.objects.get.return_value = MagicMock(dbid=NOTE_DBID)
        mock_visit_note.objects.filter.return_value.first.return_value = None

        handler = _make_api(query_params={"note_id": NOTE_UUID})
        effects = handler.load()

        resp = json.loads(effects[0].content)
        assert resp["content"] == ""
        assert resp["updated_at"] is None


class TestTabName:
    def test_defaults_to_visit_notes(self):
        handler = _make_api(query_params={})
        assert handler._tab_name() == "Visit Notes"

    def test_reads_from_secret(self):
        handler = _make_api(query_params={}, secrets={"tab_name": "Session Notes"})
        assert handler._tab_name() == "Session Notes"

    def test_query_param_overrides_secret(self):
        handler = _make_api(
            query_params={"tab_name": "Scratch%20Notes"},
            secrets={"tab_name": "Session Notes"},
        )
        assert handler._tab_name() == "Scratch Notes"
