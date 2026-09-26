"""Tests for supervisor_cosign.protocols.cosign_button."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from supervisor_cosign.protocols.cosign_button import CoSignButton


MODULE = "supervisor_cosign.protocols.cosign_button"
_DEFAULT_CONTEXT = object()


def _make_handler(context=_DEFAULT_CONTEXT, event_name="SHOW_NOTE_HEADER_BUTTON"):
    handler = CoSignButton.__new__(CoSignButton)
    handler.event = MagicMock()
    handler.event.name = event_name
    handler.event.context = {"note_id": 42} if context is _DEFAULT_CONTEXT else context
    handler.secrets = {}
    handler.environment = {}
    return handler


class TestNoteUuid:
    def test_returns_none_when_raw_is_none(self):
        handler = _make_handler(context={})
        assert handler._note_uuid() is None

    def test_returns_none_when_raw_is_empty_string(self):
        handler = _make_handler(context={"note_id": ""})
        assert handler._note_uuid() is None

    def test_returns_none_when_note_not_found(self):
        handler = _make_handler(context={"note_id": 99})
        with patch(f"{MODULE}.Note") as mock_note:
            mock_note.objects.filter.return_value.values_list.return_value.first.return_value = None
            assert handler._note_uuid() is None

    def test_returns_str_uuid_when_found(self):
        handler = _make_handler(context={"note_id": 42})
        with patch(f"{MODULE}.Note") as mock_note:
            mock_note.objects.filter.return_value.values_list.return_value.first.return_value = "note-uuid-xyz"
            assert handler._note_uuid() == "note-uuid-xyz"
            mock_note.objects.filter.assert_called_once_with(dbid=42)


class TestStaffName:
    def test_empty_staff_id(self):
        handler = _make_handler()
        assert handler._staff_name("") == ""

    def test_staff_not_found(self):
        handler = _make_handler()
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values.return_value.first.return_value = None
            assert handler._staff_name("missing") == ""

    def test_staff_found(self):
        handler = _make_handler()
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values.return_value.first.return_value = {
                "first_name": "Sara",
                "last_name": "Sup",
            }
            assert handler._staff_name("staff-1") == "Sara Sup"


class TestLatestRecord:
    def test_returns_none_when_no_note_uuid(self):
        handler = _make_handler(context={})
        assert handler._latest_record() is None

    def test_prefers_approved_record(self):
        handler = _make_handler()
        approved = MagicMock(name="approved")
        pending = MagicMock(name="pending")
        with patch.object(CoSignButton, "_note_uuid", return_value="note-1"), \
             patch(f"{MODULE}.CoSignRecord") as mock_record:
            base_qs = mock_record.objects.filter.return_value
            base_qs.filter.return_value.order_by.return_value.first.return_value = approved
            base_qs.order_by.return_value.first.return_value = pending
            assert handler._latest_record() is approved

    def test_falls_back_to_most_recent_when_no_approved(self):
        handler = _make_handler()
        pending = MagicMock(name="pending")
        with patch.object(CoSignButton, "_note_uuid", return_value="note-1"), \
             patch(f"{MODULE}.CoSignRecord") as mock_record:
            base_qs = mock_record.objects.filter.return_value
            base_qs.filter.return_value.order_by.return_value.first.return_value = None
            base_qs.order_by.return_value.first.return_value = pending
            assert handler._latest_record() is pending

    def test_returns_none_when_no_records(self):
        handler = _make_handler()
        with patch.object(CoSignButton, "_note_uuid", return_value="note-1"), \
             patch(f"{MODULE}.CoSignRecord") as mock_record:
            base_qs = mock_record.objects.filter.return_value
            base_qs.filter.return_value.order_by.return_value.first.return_value = None
            base_qs.order_by.return_value.first.return_value = None
            assert handler._latest_record() is None


class TestVisible:
    def test_true_when_record_exists(self):
        handler = _make_handler()
        with patch.object(CoSignButton, "_latest_record", return_value=MagicMock()):
            assert handler.visible() is True

    def test_false_when_no_record(self):
        handler = _make_handler()
        with patch.object(CoSignButton, "_latest_record", return_value=None):
            assert handler.visible() is False


class TestCompute:
    def test_returns_empty_for_non_matching_event_name(self):
        handler = _make_handler(event_name="SOMETHING_ELSE")
        assert handler.compute() == []

    def test_returns_empty_when_button_location_unset(self):
        handler = _make_handler()
        handler.BUTTON_LOCATION = None
        assert handler.compute() == []

    def test_skip_when_show_event_for_other_location(self):
        handler = _make_handler(event_name="SHOW_NOTE_FOOTER_BUTTON")
        with patch.object(CoSignButton, "_latest_record") as mock_latest:
            assert handler.compute() == []
            mock_latest.assert_not_called()

    def test_skip_when_no_record_for_show(self):
        handler = _make_handler(event_name="SHOW_NOTE_HEADER_BUTTON")
        with patch.object(CoSignButton, "_latest_record", return_value=None):
            assert handler.compute() == []

    def test_show_pending_title(self):
        handler = _make_handler()
        record = MagicMock(status="pending")
        sentinel = MagicMock(name="show-button-effect")
        with patch.object(CoSignButton, "_latest_record", return_value=record), \
             patch(f"{MODULE}.ShowButtonEffect") as mock_show:
            mock_show.return_value.apply.return_value = sentinel
            result = handler.compute()
            assert result == [sentinel]
            assert mock_show.call_args.kwargs["title"] == "Co-sign"
            assert mock_show.call_args.kwargs["key"] == "COSIGN_BUTTON"

    def test_show_approved_title(self):
        handler = _make_handler()
        record = MagicMock(status="approved")
        sentinel = MagicMock(name="show-button-effect")
        with patch.object(CoSignButton, "_latest_record", return_value=record), \
             patch(f"{MODULE}.ShowButtonEffect") as mock_show:
            mock_show.return_value.apply.return_value = sentinel
            result = handler.compute()
            assert result == [sentinel]
            assert mock_show.call_args.kwargs["title"] == "Co-signed ✓"

    def test_dispatches_to_handle_on_button_click(self):
        handler = _make_handler(
            event_name="ACTION_BUTTON_CLICKED",
            context={"key": "COSIGN_BUTTON"},
        )
        sentinel = [MagicMock(name="modal-effect")]
        with patch.object(CoSignButton, "handle", return_value=sentinel) as mock_handle:
            assert handler.compute() is sentinel
            mock_handle.assert_called_once()

    def test_ignores_unrelated_button_clicks(self):
        handler = _make_handler(
            event_name="ACTION_BUTTON_CLICKED",
            context={"key": "OTHER_BUTTON"},
        )
        with patch.object(CoSignButton, "handle") as mock_handle:
            assert handler.compute() == []
            mock_handle.assert_not_called()


class TestHandle:
    def test_returns_empty_when_no_note_uuid(self):
        handler = _make_handler()
        with patch.object(CoSignButton, "_note_uuid", return_value=None):
            assert handler.handle() == []

    def test_returns_empty_when_no_record(self):
        handler = _make_handler()
        with patch.object(CoSignButton, "_note_uuid", return_value="note-1"), \
             patch.object(CoSignButton, "_latest_record", return_value=None):
            assert handler.handle() == []

    def test_renders_modal_with_full_context(self):
        handler = _make_handler()
        record = MagicMock()
        record.status = "pending"
        record.cosigned_at = None
        record.supervisor_id = "sup-1"
        record.supervisee_id = "sup-2"

        note = MagicMock()
        note.patient.first_name = "Pat"
        note.patient.last_name = "Pid"
        note.datetime_of_service = datetime(2026, 5, 1, 14, 30, tzinfo=timezone.utc)

        addendum_qs = [
            {
                "addendum_text": "Approved.",
                "supervisor_name": "Sara Sup",
                "created_at": datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
            },
        ]

        captured = {}

        def fake_render(template_path, context):
            captured["template"] = template_path
            captured["context"] = context
            return "<html>rendered</html>"

        sentinel = MagicMock(name="launch-modal-effect")
        with patch.object(CoSignButton, "_note_uuid", return_value="note-uuid-1"), \
             patch.object(CoSignButton, "_latest_record", return_value=record), \
             patch.object(
                 CoSignButton,
                 "_staff_name",
                 side_effect=lambda sid: {"sup-1": "Sara Sup", "sup-2": "Lee Doc"}.get(sid, ""),
             ), \
             patch(f"{MODULE}.Note") as mock_note, \
             patch(f"{MODULE}.CoSignAddendum") as mock_addendum, \
             patch(f"{MODULE}.render_to_string", side_effect=fake_render), \
             patch(f"{MODULE}.LaunchModalEffect") as mock_modal:
            mock_note.objects.select_related.return_value.filter.return_value.first.return_value = note
            mock_addendum.objects.filter.return_value.order_by.return_value.values.return_value = addendum_qs
            mock_modal.return_value.apply.return_value = sentinel

            result = handler.handle()

            assert result == [sentinel]
            assert captured["template"] == "templates/cosign_modal.html"
            ctx = captured["context"]
            assert ctx["note_id"] == "note-uuid-1"
            assert ctx["patient_name"] == "Pat Pid"
            assert ctx["note_date"] == "2026-05-01"
            assert ctx["supervisee_name"] == "Lee Doc"
            assert ctx["approved"] is False
            assert ctx["cosigned_on"] == ""
            assert ctx["supervisor_name"] == "Sara Sup"
            assert len(ctx["addendum_entries"]) == 1
            assert ctx["addendum_entries"][0]["text"] == "Approved."
            assert ctx["addendum_entries"][0]["supervisor_name"] == "Sara Sup"
            # All four attestation templates available
            template_keys = {tpl["key"] for tpl in ctx["templates"]}
            assert template_keys == {"teaching", "reviewed", "personally_performed", "custom"}
            # Templates interpolate supervisee name
            teaching = next(t for t in ctx["templates"] if t["key"] == "teaching")
            assert "Lee Doc" in teaching["text"]

    def test_handles_missing_patient_and_dos(self):
        handler = _make_handler()
        record = MagicMock(status="approved")
        record.cosigned_at = datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc)
        record.supervisor_id = "sup-1"
        record.supervisee_id = ""

        note = MagicMock()
        note.patient = None
        note.datetime_of_service = None

        sentinel = MagicMock()
        with patch.object(CoSignButton, "_note_uuid", return_value="note-uuid-1"), \
             patch.object(CoSignButton, "_latest_record", return_value=record), \
             patch.object(CoSignButton, "_staff_name", return_value=""), \
             patch(f"{MODULE}.Note") as mock_note, \
             patch(f"{MODULE}.CoSignAddendum") as mock_addendum, \
             patch(f"{MODULE}.render_to_string", return_value="<html>"), \
             patch(f"{MODULE}.LaunchModalEffect") as mock_modal:
            mock_note.objects.select_related.return_value.filter.return_value.first.return_value = note
            mock_addendum.objects.filter.return_value.order_by.return_value.values.return_value = []
            mock_modal.return_value.apply.return_value = sentinel

            result = handler.handle()

            assert result == [sentinel]
            ctx = mock_modal.call_args  # not captured here; ensure no exceptions
            assert ctx is not None
