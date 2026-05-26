import json
from http import HTTPStatus
from typing import Union
from urllib.parse import unquote

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note

from custom_visit_notes.models.visit_note import VisitNote


class VisitNotesAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the Visit Notes UI and handles save/load."""

    PREFIX = "/notes"

    def _tab_name(self) -> str:
        param = self.request.query_params.get("tab_name", "")
        if param:
            return unquote(param)
        return self.secrets.get("tab_name", "Visit Notes")

    @api.get("/app")
    def get_app(self) -> list[Union[Response, Effect]]:
        note_uuid = self.request.query_params.get("note_id", "")
        if not note_uuid:
            return [
                HTMLResponse(
                    "<html><body>Error: note_id is required</body></html>",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            note = Note.objects.get(id=note_uuid)
        except Note.DoesNotExist:
            return [
                HTMLResponse(
                    "<html><body>Error: note not found</body></html>",
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        existing = VisitNote.objects.filter(note_id=note.dbid).first()
        content = existing.content if existing else ""

        html = render_to_string(
            "templates/visit_notes.html",
            {
                "note_id_json": json.dumps(note_uuid),
                "content": json.dumps(content),
                "tab_name": self._tab_name(),
            },
        )
        return [HTMLResponse(html)]

    @api.get("/load")
    def load(self) -> list[Union[Response, Effect]]:
        note_uuid = self.request.query_params.get("note_id", "")
        if not note_uuid:
            return [JSONResponse({"error": "note_id required"}, status_code=HTTPStatus.BAD_REQUEST)]

        try:
            note = Note.objects.get(id=note_uuid)
        except Note.DoesNotExist:
            return [JSONResponse({"error": "note not found"}, status_code=HTTPStatus.NOT_FOUND)]

        existing = VisitNote.objects.filter(note_id=note.dbid).first()
        return [JSONResponse({
            "content": existing.content if existing else "",
            "updated_at": existing.updated_at.isoformat() if existing else None,
        })]

    @api.post("/save")
    def save(self) -> list[Union[Response, Effect]]:
        note_uuid = self.request.query_params.get("note_id", "")
        if not note_uuid:
            return [JSONResponse({"error": "note_id required"}, status_code=HTTPStatus.BAD_REQUEST)]

        body = self.request.json() or {}
        content = body.get("content", "")

        try:
            note = Note.objects.get(id=note_uuid)
        except Note.DoesNotExist:
            return [JSONResponse({"error": "note not found"}, status_code=HTTPStatus.NOT_FOUND)]

        visit_note, _created = VisitNote.objects.update_or_create(
            note_id=note.dbid,
            defaults={"content": content},
        )

        return [JSONResponse({
            "status": "saved",
            "updated_at": visit_note.updated_at.isoformat(),
        })]
