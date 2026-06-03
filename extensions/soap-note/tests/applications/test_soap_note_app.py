from unittest.mock import MagicMock, call

from soap_note.applications.soap_note_app import SoapNoteApp, _CACHE_BUST


def test_soap_note_app_visible():
    app = SoapNoteApp.__new__(SoapNoteApp)
    assert app.visible() is True


def test_soap_note_app_not_open_by_default():
    app = SoapNoteApp.__new__(SoapNoteApp)
    assert app.open_by_default() is False


def test_soap_note_app_identifier():
    assert SoapNoteApp.IDENTIFIER == "soap_note__charting"


def test_soap_note_app_name():
    assert SoapNoteApp.NAME == "SOAP Charting"


def test_soap_note_app_on_open():
    app = SoapNoteApp.__new__(SoapNoteApp)
    app.event = MagicMock()
    app.event.context = {"note": {"id": "test-note-uuid"}}

    result = app.on_open()

    # on_open returns an Effect from LaunchModalEffect.apply()
    assert result is not None


def test_cache_bust_is_numeric_string():
    assert _CACHE_BUST.isdigit()
    assert len(_CACHE_BUST) == 10  # Unix timestamp length
