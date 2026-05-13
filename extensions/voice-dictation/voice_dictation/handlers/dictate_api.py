import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Union

from canvas_sdk.commands.commands.history_present_illness import HistoryOfPresentIllnessCommand
from canvas_sdk.commands.commands.plan import PlanCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils import Http
from logger import log

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

CONTENT_TYPES = {
    "js": "text/javascript",
    "css": "text/css",
}


class DictateAPI(StaffSessionAuthMixin, SimpleAPI):
    """API for voice dictation — serves recording UI and handles transcription."""

    PREFIX = "/dictate"

    @api.get("/app")
    def get_app(self) -> list[Union[Response, Effect]]:
        """Serve the recording UI inside the note tab."""
        note_uuid = self.request.query_params.get("note_id", "")
        if not note_uuid:
            return [HTMLResponse("<html><body>Error: note_id required</body></html>", status_code=HTTPStatus.BAD_REQUEST)]

        html = render_to_string(
            "templates/record.html",
            {"note_uuid": note_uuid, "cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.post("/transcribe")
    def transcribe_audio(self) -> list[Union[JSONResponse, Effect]]:
        """Receive audio, transcribe via ElevenLabs batch API, return transcript text."""
        api_key = self.secrets.get("ELEVENLABS_API_KEY")
        if not api_key:
            return [JSONResponse({"error": "ELEVENLABS_API_KEY not configured"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

        form_data = self.request.form_data()
        audio_part = form_data.get("audio")
        if not audio_part or not audio_part.is_file():
            return [JSONResponse({"error": "No audio file provided"}, status_code=HTTPStatus.BAD_REQUEST)]

        transcript = self._call_elevenlabs_stt(api_key, audio_part.content, audio_part.content_type)
        if transcript is None:
            return [JSONResponse({"error": "Transcription failed"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

        if not transcript.strip():
            return [JSONResponse({"error": "No speech detected"}, status_code=HTTPStatus.BAD_REQUEST)]

        return [JSONResponse({"transcript": transcript}, status_code=HTTPStatus.OK)]

    @api.get("/static/<filename>")
    def get_static(self) -> list[Union[Response, Effect]]:
        """Serve static JS/CSS files."""
        filename = self.request.path_params["filename"]
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        content_type = CONTENT_TYPES.get(ext)
        if not content_type:
            return [Response(b"Not found", status_code=HTTPStatus.NOT_FOUND)]

        content = render_to_string(f"static/{filename}")
        return [Response(content.encode(), status_code=HTTPStatus.OK, content_type=content_type)]

    @api.post("/create/<command_type>")
    def create_command(self) -> list[Union[JSONResponse, Effect]]:
        """Create an HPI or Plan command from finalized transcript text."""
        command_type = self.request.path_params["command_type"]
        note_uuid = self.request.query_params.get("note_id", "").strip()

        if command_type not in ("hpi", "plan"):
            return [JSONResponse({"error": "Invalid command type"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not note_uuid:
            return [JSONResponse({"error": "Missing note_id"}, status_code=HTTPStatus.BAD_REQUEST)]

        form_data = self.request.form_data()
        transcript_part = form_data.get("transcript")
        if not transcript_part:
            return [JSONResponse({"error": "No transcript provided"}, status_code=HTTPStatus.BAD_REQUEST)]

        transcript = transcript_part.value.strip()
        if not transcript:
            return [JSONResponse({"error": "Transcript is empty"}, status_code=HTTPStatus.BAD_REQUEST)]

        if command_type == "hpi":
            command = HistoryOfPresentIllnessCommand(note_uuid=note_uuid, narrative=transcript)
        else:
            command = PlanCommand(note_uuid=note_uuid, narrative=transcript)

        effect = command.originate()
        log.info(f"Created {command_type} command for note {note_uuid}")

        return [
            JSONResponse({"status": "created"}, status_code=HTTPStatus.OK),
            effect,
        ]

    def _call_elevenlabs_stt(self, api_key: str, audio_bytes: bytes, content_type: str) -> str | None:
        """Call ElevenLabs Speech-to-Text batch API. Returns transcript text or None on failure."""
        boundary = f"----boundary{uuid.uuid4().hex}"
        mime = content_type or "audio/webm"

        body = f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="model_id"\r\n\r\nscribe_v1\r\n'
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="file"; filename="recording.webm"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        body += audio_bytes
        body += f"\r\n--{boundary}--\r\n".encode()

        http = Http()
        response = http.post(
            ELEVENLABS_STT_URL,
            data=body,
            headers={"xi-api-key": api_key, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

        if not response.ok:
            log.error(f"ElevenLabs STT failed: {response.status_code} - {response.text}")
            return None

        return response.json().get("text", "")
