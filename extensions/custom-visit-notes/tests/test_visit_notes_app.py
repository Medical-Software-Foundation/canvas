from unittest.mock import MagicMock

from custom_visit_notes.applications.visit_notes_app import VisitNotesApp


def _make_app(note_uuid="", secrets=None):
    app = VisitNotesApp.__new__(VisitNotesApp)
    app.event = MagicMock()
    app.event.context = {"note": {"id": note_uuid}}
    app.secrets = secrets or {}
    return app


NOTE_UUID = "eb618d69-52df-4ac0-8ac0-9a457ee15981"


class TestVisitNotesApp:
    def test_visible_returns_true(self):
        app = _make_app()
        assert app.visible() is True

    def test_open_by_default_returns_false(self):
        app = _make_app()
        assert app.open_by_default() is False

    def test_on_open_returns_launch_modal_effect(self):
        app = _make_app(note_uuid=NOTE_UUID, secrets={"tab_name": "Therapy Notes"})
        effect = app.on_open()
        assert effect is not None
        assert "LaunchModal" in type(effect).__name__ or hasattr(effect, "payload")

    def test_on_open_uses_tab_name_from_secret(self):
        app = _make_app(note_uuid=NOTE_UUID, secrets={"tab_name": "Session Notes"})
        effect = app.on_open()
        payload = effect.payload if isinstance(effect.payload, dict) else {}
        url = payload.get("url", str(effect.payload))
        assert "tab_name=Session Notes" in url

    def test_on_open_defaults_tab_name(self):
        app = _make_app(note_uuid=NOTE_UUID)
        effect = app.on_open()
        payload = effect.payload if isinstance(effect.payload, dict) else {}
        url = payload.get("url", str(effect.payload))
        assert "tab_name=Visit Notes" in url
