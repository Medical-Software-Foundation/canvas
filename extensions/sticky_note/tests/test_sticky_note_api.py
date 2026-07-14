import json
from unittest.mock import MagicMock, call, patch

from sticky_note.protocols.sticky_note_api import (
    StickyNoteAPI,
    _save_note,
)


def _make_api(query_params=None, body=None, secrets=None):
    request = MagicMock()
    request.query_params = query_params or {}
    request.body = json.dumps(body) if body else ""

    handler = StickyNoteAPI.__new__(StickyNoteAPI)
    handler.request = request
    handler.secrets = secrets or {}
    return handler


PATIENT_DBID = 42
STAFF_DBID = 99


class TestStickyNoteAPIGet:
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_staff_dbid",
        return_value=STAFF_DBID,
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_patient_dbid",
        return_value=PATIENT_DBID,
    )
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_get_returns_notes(self, mock_model, mock_patient, mock_staff):
        shared_qs = MagicMock()
        shared_qs.values.return_value.first.return_value = {
            "content": "shared content",
            "updated_by": "Jane Doe",
            "updated_by_id": "s-456",
            "updated_at": None,
            "version": 3,
        }

        user_qs = MagicMock()
        user_qs.values.return_value.first.return_value = {
            "content": "user content",
            "version": 1,
        }

        def filter_side_effect(**kwargs):
            if kwargs.get("owner_id__isnull"):
                return shared_qs
            return user_qs

        mock_model.objects.filter.side_effect = filter_side_effect

        handler = _make_api(query_params={"patient_id": "p-123", "staff_id": "s-456"})
        effects = handler.get()

        assert len(effects) == 1

    def test_get_missing_params(self):
        handler = _make_api(query_params={})
        effects = handler.get()
        assert len(effects) == 1


class TestStickyNoteAPIPost:
    @patch(
        "sticky_note.protocols.sticky_note_api._save_note",
        return_value={"status": "ok", "version": 1},
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_staff",
        return_value=(STAFF_DBID, "Jane Doe"),
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_patient_dbid",
        return_value=PATIENT_DBID,
    )
    @patch("sticky_note.protocols.sticky_note_api.ReloadPatientActionButtonsEffect")
    def test_post_saves_shared_note(
        self, mock_reload, mock_patient, mock_staff, mock_save
    ):
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "shared",
                "content": "hello team",
                "version": 0,
            },
        )
        effects = handler.post()

        assert len(effects) == 2
        mock_reload.assert_called_once_with(id="p-123")
        mock_save.assert_called_once_with(
            patient_dbid=PATIENT_DBID,
            patient_uuid="p-123",
            owner_id=None,
            note_type="shared",
            content="hello team",
            staff_uuid="s-456",
            staff_name="Jane Doe",
            expected_version=0,
            audit=False,
        )

    @patch(
        "sticky_note.protocols.sticky_note_api._save_note",
        return_value={"status": "ok", "version": 1},
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_staff",
        return_value=(STAFF_DBID, "Jane Doe"),
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_patient_dbid",
        return_value=PATIENT_DBID,
    )
    @patch("sticky_note.protocols.sticky_note_api.ReloadPatientActionButtonsEffect")
    def test_post_saves_user_note(
        self, mock_reload, mock_patient, mock_staff, mock_save
    ):
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "user",
                "content": "my private note",
                "version": 0,
            },
        )
        effects = handler.post()

        assert len(effects) == 2
        mock_reload.assert_called_once_with(id="p-123")
        mock_save.assert_called_once_with(
            patient_dbid=PATIENT_DBID,
            patient_uuid="p-123",
            owner_id=STAFF_DBID,
            note_type="user",
            content="my private note",
            staff_uuid="s-456",
            staff_name="Jane Doe",
            expected_version=0,
            audit=False,
        )

    def test_post_invalid_json(self):
        handler = StickyNoteAPI.__new__(StickyNoteAPI)
        handler.request = MagicMock()
        handler.request.body = "not json"
        handler.secrets = {}
        effects = handler.post()
        assert len(effects) == 1

    def test_post_missing_fields(self):
        handler = _make_api(body={"patient_id": "p-123"})
        effects = handler.post()
        assert len(effects) == 1

    def test_post_invalid_type(self):
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "invalid",
                "content": "test",
                "version": 0,
            },
        )
        effects = handler.post()
        assert len(effects) == 1

    def test_post_invalid_version(self):
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "shared",
                "content": "test",
                "version": "not-a-number",
            },
        )
        effects = handler.post()
        assert len(effects) == 1

    def test_post_content_too_long(self):
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "shared",
                "content": "x" * 4097,
                "version": 0,
            },
        )
        effects = handler.post()
        assert len(effects) == 1

    @patch(
        "sticky_note.protocols.sticky_note_api._save_note",
        return_value={"status": "ok", "version": 2},
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_staff",
        return_value=(STAFF_DBID, "Jane Doe"),
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_patient_dbid",
        return_value=PATIENT_DBID,
    )
    @patch("sticky_note.protocols.sticky_note_api.ReloadPatientActionButtonsEffect")
    def test_post_passes_audit_true(
        self, mock_reload, mock_patient, mock_staff, mock_save
    ):
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "shared",
                "content": "final content",
                "version": 1,
                "audit": True,
            },
        )
        effects = handler.post()

        assert len(effects) == 2
        mock_reload.assert_called_once_with(id="p-123")
        mock_save.assert_called_once_with(
            patient_dbid=PATIENT_DBID,
            patient_uuid="p-123",
            owner_id=None,
            note_type="shared",
            content="final content",
            staff_uuid="s-456",
            staff_name="Jane Doe",
            expected_version=1,
            audit=True,
        )

    @patch(
        "sticky_note.protocols.sticky_note_api._save_note",
        return_value={"status": "ok", "version": 3},
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_staff",
        return_value=(STAFF_DBID, "Jane Doe"),
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_patient_dbid",
        return_value=PATIENT_DBID,
    )
    @patch("sticky_note.protocols.sticky_note_api.ReloadPatientActionButtonsEffect")
    def test_post_audit_defaults_false(
        self, mock_reload, mock_patient, mock_staff, mock_save
    ):
        """Omitting audit from body should pass audit=False to _save_note."""
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "shared",
                "content": "debounce save",
                "version": 2,
            },
        )
        handler.post()

        mock_save.assert_called_once()
        assert mock_save.call_args == call(
            patient_dbid=PATIENT_DBID,
            patient_uuid="p-123",
            owner_id=None,
            note_type="shared",
            content="debounce save",
            staff_uuid="s-456",
            staff_name="Jane Doe",
            expected_version=2,
            audit=False,
        )

    @patch(
        "sticky_note.protocols.sticky_note_api._save_note",
        return_value={"status": "conflict", "version": 5},
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_staff",
        return_value=(STAFF_DBID, "Jane Doe"),
    )
    @patch(
        "sticky_note.protocols.sticky_note_api._resolve_patient_dbid",
        return_value=PATIENT_DBID,
    )
    @patch("sticky_note.protocols.sticky_note_api.ReloadPatientActionButtonsEffect")
    def test_post_conflict_does_not_reload(
        self, mock_reload, mock_patient, mock_staff, mock_save
    ):
        """A version conflict returns only the JSON response, no button reload."""
        handler = _make_api(
            body={
                "patient_id": "p-123",
                "staff_id": "s-456",
                "type": "shared",
                "content": "racing edit",
                "version": 1,
            },
        )
        effects = handler.post()

        assert len(effects) == 1
        mock_reload.assert_not_called()


class TestSaveNoteAuditGating:
    """Verify _save_note writes audit only when audit=True."""

    @patch("sticky_note.protocols.sticky_note_api._write_audit")
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_edit_without_audit_skips_write_audit(self, mock_model, mock_audit):
        """Debounce saves (audit=False) should NOT write audit."""
        mock_model.objects.filter.return_value.values.return_value.first.return_value = {
            "content": "old",
            "version": 1,
            "updated_by": "Jane",
            "updated_by_id": "s-1",
            "updated_at": None,
        }
        mock_model.objects.filter.return_value.update.return_value = 1

        result = _save_note(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", content="new", staff_uuid="s-1",
            staff_name="Jane", expected_version=1, audit=False,
        )

        assert result["status"] == "ok"
        mock_audit.assert_not_called()

    @patch("sticky_note.protocols.sticky_note_api._write_audit")
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_edit_with_audit_writes_audit(self, mock_model, mock_audit):
        """Session-end save (audit=True) SHOULD write audit."""
        mock_model.objects.filter.return_value.values.return_value.first.return_value = {
            "content": "old",
            "version": 1,
            "updated_by": "Jane",
            "updated_by_id": "s-1",
            "updated_at": None,
        }
        mock_model.objects.filter.return_value.update.return_value = 1

        result = _save_note(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", content="new", staff_uuid="s-1",
            staff_name="Jane", expected_version=1, audit=True,
        )

        assert result["status"] == "ok"
        mock_audit.assert_called_once_with(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", action="edited", content="new",
            staff_uuid="s-1", staff_name="Jane",
        )

    @patch("sticky_note.protocols.sticky_note_api._write_audit")
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_unchanged_content_with_audit_writes_audit(self, mock_model, mock_audit):
        """Content unchanged + audit=True (debounce already saved) writes audit."""
        mock_model.objects.filter.return_value.values.return_value.first.return_value = {
            "content": "same",
            "version": 5,
            "updated_by": "Jane",
            "updated_by_id": "s-1",
            "updated_at": None,
        }

        result = _save_note(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", content="same", staff_uuid="s-1",
            staff_name="Jane", expected_version=5, audit=True,
        )

        assert result["status"] == "ok"
        assert result["version"] == 5
        mock_audit.assert_called_once_with(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", action="edited", content="same",
            staff_uuid="s-1", staff_name="Jane",
        )

    @patch("sticky_note.protocols.sticky_note_api._write_audit")
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_unchanged_content_without_audit_skips_audit(self, mock_model, mock_audit):
        """Content unchanged + audit=False — no audit, no version bump."""
        mock_model.objects.filter.return_value.values.return_value.first.return_value = {
            "content": "same",
            "version": 5,
            "updated_by": "Jane",
            "updated_by_id": "s-1",
            "updated_at": None,
        }

        result = _save_note(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", content="same", staff_uuid="s-1",
            staff_name="Jane", expected_version=5, audit=False,
        )

        assert result["status"] == "ok"
        mock_audit.assert_not_called()

    @patch("sticky_note.protocols.sticky_note_api._write_audit")
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_create_without_audit_skips_write_audit(self, mock_model, mock_audit):
        """New note creation without audit flag skips audit."""
        mock_model.objects.filter.return_value.values.return_value.first.return_value = None

        result = _save_note(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", content="first note", staff_uuid="s-1",
            staff_name="Jane", expected_version=0, audit=False,
        )

        assert result["status"] == "ok"
        assert result["version"] == 1
        mock_audit.assert_not_called()

    @patch("sticky_note.protocols.sticky_note_api._write_audit")
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_create_with_audit_writes_audit(self, mock_model, mock_audit):
        """New note creation with audit=True writes 'created' audit."""
        mock_model.objects.filter.return_value.values.return_value.first.return_value = None

        result = _save_note(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", content="first note", staff_uuid="s-1",
            staff_name="Jane", expected_version=0, audit=True,
        )

        assert result["status"] == "ok"
        mock_audit.assert_called_once_with(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", action="created", content="first note",
            staff_uuid="s-1", staff_name="Jane",
        )

    @patch("sticky_note.protocols.sticky_note_api._write_audit")
    @patch("sticky_note.protocols.sticky_note_api.StickyNote")
    def test_cleared_note_with_audit(self, mock_model, mock_audit):
        """Empty content + audit=True writes 'cleared' action."""
        mock_model.objects.filter.return_value.values.return_value.first.return_value = {
            "content": "had text",
            "version": 2,
            "updated_by": "Jane",
            "updated_by_id": "s-1",
            "updated_at": None,
        }
        mock_model.objects.filter.return_value.update.return_value = 1

        result = _save_note(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", content="", staff_uuid="s-1",
            staff_name="Jane", expected_version=2, audit=True,
        )

        assert result["status"] == "ok"
        mock_audit.assert_called_once()
        assert mock_audit.call_args == call(
            patient_dbid=1, patient_uuid="p-1", owner_id=None,
            note_type="shared", action="cleared", content="",
            staff_uuid="s-1", staff_name="Jane",
        )
