"""Cover _find_open_note and the Application handler."""
from unittest.mock import MagicMock

from order_sets.api import endpoints
from order_sets.api.endpoints import OrderSetsAPI
from order_sets.applications.order_sets_admin_app import OrderSetsAdminApp
from order_sets.applications.order_sets_app import OrderSetsApp


class TestFindOpenNote:
    def _make_handler(self):
        handler = OrderSetsAPI.__new__(OrderSetsAPI)
        handler.request = MagicMock()
        handler.request.headers = {}
        return handler

    def test_returns_note_and_provider_id(self, monkeypatch):
        cnse_objects = MagicMock()
        cnse_objects.filter.return_value.values_list.return_value = [1, 2, 3]
        monkeypatch.setattr(endpoints.CurrentNoteStateEvent, "objects", cnse_objects)

        provider = MagicMock(id="provider-1")
        note = MagicMock(id="note-uuid", provider=provider)
        note_objects = MagicMock()
        note_objects.filter.return_value.select_related.return_value.order_by.return_value.first.return_value = note
        monkeypatch.setattr(endpoints.Note, "objects", note_objects)

        handler = self._make_handler()
        note_uuid, provider_key = handler._find_open_note("p-1")
        assert note_uuid == "note-uuid"
        assert provider_key == "provider-1"

    def test_returns_nulls_when_no_open_note(self, monkeypatch):
        cnse_objects = MagicMock()
        cnse_objects.filter.return_value.values_list.return_value = []
        monkeypatch.setattr(endpoints.CurrentNoteStateEvent, "objects", cnse_objects)

        note_objects = MagicMock()
        note_objects.filter.return_value.select_related.return_value.order_by.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Note, "objects", note_objects)

        handler = self._make_handler()
        note_uuid, provider_key = handler._find_open_note("p-1")
        assert note_uuid is None
        assert provider_key == ""

    def test_note_without_provider_returns_empty_provider_key(self, monkeypatch):
        cnse_objects = MagicMock()
        cnse_objects.filter.return_value.values_list.return_value = [1]
        monkeypatch.setattr(endpoints.CurrentNoteStateEvent, "objects", cnse_objects)

        note = MagicMock(id="note-1", provider=None)
        note_objects = MagicMock()
        note_objects.filter.return_value.select_related.return_value.order_by.return_value.first.return_value = note
        monkeypatch.setattr(endpoints.Note, "objects", note_objects)

        handler = self._make_handler()
        note_uuid, provider_key = handler._find_open_note("p-1")
        assert note_uuid == "note-1"
        assert provider_key == ""


class TestOrderSetsApp:
    def test_on_open_emits_modal_with_patient_id(self):
        app = OrderSetsApp.__new__(OrderSetsApp)
        app.event = MagicMock()
        app.event.context = {"patient": {"id": "patient-42"}}

        effect = app.on_open()
        # The mocked LaunchModalEffect.apply() returns a MagicMock with the
        # original content/target, so we can re-derive the HTML.
        # The test conftest's _LaunchModalEffect stores content/target on the
        # apply() return.
        assert "patient-42" in effect.content

    def test_on_open_handles_missing_patient_id(self):
        app = OrderSetsApp.__new__(OrderSetsApp)
        app.event = MagicMock()
        app.event.context = {}

        effect = app.on_open()
        # json.dumps("") → '""'; should appear in the script
        assert '""' in effect.content

    def test_on_open_blocks_script_tag_breakout(self):
        """Inline-script breakout via `</script>` must be escaped.

        `json.dumps` alone does NOT escape `</script>`; the HTML tokenizer
        terminates the script element at the literal closing tag regardless
        of JS string context. The application's `_js_safe` helper has to
        replace `</` with `<\\/` so the tokenizer never sees a closing tag.
        """
        app = OrderSetsApp.__new__(OrderSetsApp)
        app.event = MagicMock()
        app.event.context = {"patient": {"id": '</script><script>alert(1)//'}}

        effect = app.on_open()
        assert effect.content.count("</script>") == 1
        assert "<\\/script>" in effect.content


class TestOrderSetsAdminApp:
    def test_on_open_does_not_require_patient_context(self):
        """The global-scope admin app must work with no patient context.

        Per REVIEW.md item #10, admin operations should be reachable from a
        global app — not gated behind opening a patient chart.
        """
        app = OrderSetsAdminApp.__new__(OrderSetsAdminApp)
        # Deliberately do NOT set app.event — on_open must not read patient context.
        effect = app.on_open()

        # Fetches /admin-ui directly with no patient_id query string
        assert "/admin-ui" in effect.content
        assert "patient_id" not in effect.content
