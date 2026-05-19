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
    def test_on_open_emits_modal_url_with_patient_id(self):
        app = OrderSetsApp.__new__(OrderSetsApp)
        app.event = MagicMock()
        app.event.context = {"patient": {"id": "patient-42"}}

        effect = app.on_open()
        assert effect.url == "/plugin-io/api/order_sets/ui?patient_id=patient-42"

    def test_on_open_handles_missing_patient_id(self):
        app = OrderSetsApp.__new__(OrderSetsApp)
        app.event = MagicMock()
        app.event.context = {}

        effect = app.on_open()
        assert effect.url == "/plugin-io/api/order_sets/ui?patient_id="

    def test_on_open_url_encodes_unsafe_chars_in_patient_id(self):
        """Patient id is interpolated into a URL query string and must be
        percent-encoded so reserved characters can't break the request.
        """
        app = OrderSetsApp.__new__(OrderSetsApp)
        app.event = MagicMock()
        app.event.context = {"patient": {"id": "a&b=c#d"}}

        effect = app.on_open()
        assert effect.url == "/plugin-io/api/order_sets/ui?patient_id=a%26b%3Dc%23d"


class TestOrderSetsAdminApp:
    def test_on_open_does_not_require_patient_context(self):
        """The global-scope admin app must work with no patient context.

        Per REVIEW.md item #10, admin operations should be reachable from a
        global app — not gated behind opening a patient chart.
        """
        app = OrderSetsAdminApp.__new__(OrderSetsAdminApp)
        # Deliberately do NOT set app.event — on_open must not read patient context.
        effect = app.on_open()

        assert effect.url == "/plugin-io/api/order_sets/admin-ui"
