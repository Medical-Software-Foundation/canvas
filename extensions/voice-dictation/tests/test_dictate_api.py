import json
import re
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response

from voice_dictation.handlers.dictate_api import DictateAPI, ELEVENLABS_STT_URL


def _make_api(method="GET", path="/dictate/app", secrets=None, query_params=None, path_params=None):
    """Create a DictateAPI instance with mocked internals."""
    event = SimpleNamespace(context={"method": method, "path": path})
    instance = DictateAPI(event, secrets if secrets is not None else {"ELEVENLABS_API_KEY": "test-key"}, {})
    instance._path_pattern = re.compile(r".*")
    instance.request = SimpleNamespace(
        headers={"canvas-logged-in-user-id": "staff-1"},
        query_params=query_params or {},
        path_params=path_params or {},
        body=b"",
    )
    return instance


def _file_part(content=b"audio-data", content_type="audio/webm"):
    part = MagicMock()
    part.is_file.return_value = True
    part.content = content
    part.content_type = content_type
    return part


def _string_part(value):
    part = MagicMock()
    part.is_file.return_value = False
    part.value = value
    return part


# ── get_app ──────────────────────────────────────────────────────────────────


@patch("voice_dictation.handlers.dictate_api.render_to_string")
def test_get_app_success(mock_render):
    mock_render.return_value = "<html>ok</html>"
    api = _make_api(query_params={"note_id": "uuid-1"})
    result = api.get_app()

    assert len(result) == 1
    assert isinstance(result[0], HTMLResponse)
    ctx = mock_render.call_args.args[1]
    assert ctx["note_uuid"] == "uuid-1"
    assert "cache_bust" in ctx


def test_get_app_missing_note_id():
    api = _make_api(query_params={})
    result = api.get_app()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


# ── transcribe_audio ─────────────────────────────────────────────────────────


@patch("voice_dictation.handlers.dictate_api.Http")
def test_transcribe_success(mock_http_cls):
    resp = MagicMock(ok=True)
    resp.json.return_value = {"text": "Patient has chest pain."}
    mock_http_cls.return_value.post.return_value = resp

    api = _make_api(method="POST", path="/dictate/transcribe")
    api.request.form_data = lambda: {"audio": _file_part()}
    result = api.transcribe_audio()

    assert json.loads(result[0].content)["transcript"] == "Patient has chest pain."


def test_transcribe_missing_api_key():
    api = _make_api(method="POST", path="/dictate/transcribe", secrets={})
    result = api.transcribe_audio()
    assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_transcribe_no_audio():
    api = _make_api(method="POST", path="/dictate/transcribe")
    api.request.form_data = lambda: {}
    result = api.transcribe_audio()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_transcribe_non_file():
    api = _make_api(method="POST", path="/dictate/transcribe")
    part = MagicMock()
    part.is_file.return_value = False
    api.request.form_data = lambda: {"audio": part}
    result = api.transcribe_audio()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


@patch("voice_dictation.handlers.dictate_api.Http")
def test_transcribe_api_failure(mock_http_cls):
    resp = MagicMock(ok=False, status_code=500, text="error")
    mock_http_cls.return_value.post.return_value = resp

    api = _make_api(method="POST", path="/dictate/transcribe")
    api.request.form_data = lambda: {"audio": _file_part()}
    result = api.transcribe_audio()
    assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@patch("voice_dictation.handlers.dictate_api.Http")
def test_transcribe_empty_speech(mock_http_cls):
    resp = MagicMock(ok=True)
    resp.json.return_value = {"text": "   "}
    mock_http_cls.return_value.post.return_value = resp

    api = _make_api(method="POST", path="/dictate/transcribe")
    api.request.form_data = lambda: {"audio": _file_part()}
    result = api.transcribe_audio()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


# ── get_static ───────────────────────────────────────────────────────────────


@patch("voice_dictation.handlers.dictate_api.render_to_string")
def test_get_static_js(mock_render):
    mock_render.return_value = "var x=1;"
    api = _make_api(path="/dictate/static/main.js", path_params={"filename": "main.js"})
    result = api.get_static()
    assert isinstance(result[0], Response)
    mock_render.assert_called_once_with("static/main.js")


@patch("voice_dictation.handlers.dictate_api.render_to_string")
def test_get_static_css(mock_render):
    mock_render.return_value = "body{}"
    api = _make_api(path="/dictate/static/styles.css", path_params={"filename": "styles.css"})
    result = api.get_static()
    assert isinstance(result[0], Response)


def test_get_static_unknown_ext():
    api = _make_api(path="/dictate/static/data.json", path_params={"filename": "data.json"})
    result = api.get_static()
    assert result[0].status_code == HTTPStatus.NOT_FOUND


# ── create_command ───────────────────────────────────────────────────────────


def test_create_hpi():
    api = _make_api(method="POST", path="/dictate/create/hpi", path_params={"command_type": "hpi"}, query_params={"note_id": "n1"})
    api.request.form_data = lambda: {"transcript": _string_part("Headache for 3 days.")}
    result = api.create_command()
    assert json.loads(result[0].content)["status"] == "created"
    assert len(result) == 2


def test_create_plan():
    api = _make_api(method="POST", path="/dictate/create/plan", path_params={"command_type": "plan"}, query_params={"note_id": "n2"})
    api.request.form_data = lambda: {"transcript": _string_part("Follow up in 2 weeks.")}
    result = api.create_command()
    assert json.loads(result[0].content)["status"] == "created"
    assert len(result) == 2


def test_create_invalid_type():
    api = _make_api(method="POST", path="/dictate/create/assessment", path_params={"command_type": "assessment"}, query_params={"note_id": "n3"})
    result = api.create_command()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_create_missing_note_id():
    api = _make_api(method="POST", path="/dictate/create/hpi", path_params={"command_type": "hpi"})
    result = api.create_command()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_create_no_transcript():
    api = _make_api(method="POST", path="/dictate/create/hpi", path_params={"command_type": "hpi"}, query_params={"note_id": "n4"})
    api.request.form_data = lambda: {}
    result = api.create_command()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_create_empty_transcript():
    api = _make_api(method="POST", path="/dictate/create/hpi", path_params={"command_type": "hpi"}, query_params={"note_id": "n5"})
    api.request.form_data = lambda: {"transcript": _string_part("   ")}
    result = api.create_command()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


# ── _call_elevenlabs_stt ─────────────────────────────────────────────────────


@patch("voice_dictation.handlers.dictate_api.Http")
def test_stt_success(mock_http_cls):
    resp = MagicMock(ok=True)
    resp.json.return_value = {"text": "hello"}
    mock_http_cls.return_value.post.return_value = resp

    api = _make_api()
    result = api._call_elevenlabs_stt("key", b"audio", "audio/webm")
    assert result == "hello"

    call_kwargs = mock_http_cls.return_value.post.call_args
    assert call_kwargs.args[0] == ELEVENLABS_STT_URL
    assert b"scribe_v1" in call_kwargs.kwargs["data"]


@patch("voice_dictation.handlers.dictate_api.Http")
def test_stt_failure(mock_http_cls):
    resp = MagicMock(ok=False, status_code=401, text="Unauthorized")
    mock_http_cls.return_value.post.return_value = resp

    api = _make_api()
    assert api._call_elevenlabs_stt("bad", b"audio", "audio/webm") is None


@patch("voice_dictation.handlers.dictate_api.Http")
def test_stt_default_content_type(mock_http_cls):
    resp = MagicMock(ok=True)
    resp.json.return_value = {"text": "hi"}
    mock_http_cls.return_value.post.return_value = resp

    api = _make_api()
    api._call_elevenlabs_stt("key", b"audio", "")
    body = mock_http_cls.return_value.post.call_args.kwargs["data"]
    assert b"audio/webm" in body
