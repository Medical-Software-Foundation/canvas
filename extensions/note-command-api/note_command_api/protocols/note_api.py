from http import HTTPStatus
from typing import Any
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPIRoute
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.practicelocation import PracticeLocationPOS
from logger import log
class NoteCommandAPI(APIKeyAuthMixin, SimpleAPIRoute):
    """
    SimpleAPI endpoint that returns note data with enhanced command attributes.
    GET /note/<note_id> - Returns all note attributes with command data populated in body.
    """
    PATH = "/note/<note_id>"
    def get(self) -> list[Response | Effect]:
        """
        Retrieve a note by ID and enhance its body with command attributes.
        Returns all Note model fields with the body array enhanced to include
        command attributes from the data module.
        """
        note_id = self.request.path_params.get("note_id")
        if not note_id:
            return [
                JSONResponse(
                    {"error": "Note ID is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        try:
            note = Note.objects.get(id=note_id)
        except Note.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Note not found", "note_id": note_id},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        note_data = self._serialize_note(note)
        log.info(f"Note data: {note_data}")
        return [JSONResponse(note_data, status_code=HTTPStatus.OK)]

    def _serialize_note(self, note: Note) -> dict[str, Any]:
        """
        Serialize all Note model attributes and enhance body with command data.
        """
        enhanced_body = self._enhance_body_with_commands(note.body)
        note_data = {
            "id": str(note.id),
            "dbid": note.dbid,
            "created": note.created.isoformat() if note.created else None,
            "modified": note.modified.isoformat() if note.modified else None,
            "current_state": note.current_state.values_list('state', flat=True)[0],
            "state_history": [
                {
                    "state": state.state,
                    "created": state.created.isoformat() if state.created else None,
                    "originator": {
                        "id": str(state.originator.person_subclass.id),
                        "first_name": state.originator.person_subclass.first_name,
                        "last_name": state.originator.person_subclass.last_name,
                        "is_staff": state.originator.is_staff,
                    } if state.originator else None,
                } for state in note.state_history.all()
            ],
            "patient": {
                "id": str(note.patient.id),
                "first_name": note.patient.first_name,
                "last_name": note.patient.last_name,
                "birth_date": note.patient.birth_date.isoformat() if note.patient.birth_date else None,
            } if note.patient else None,
            "note_type_version": {
                "name": note.note_type_version.name if note.note_type_version else None,
                "display": note.note_type_version.display if note.note_type_version else None,
                "code": note.note_type_version.code if note.note_type_version else None,
            } if note.note_type_version else None,
            "title": note.title,
            "originator": {
                "id": str(note.originator.person_subclass.id),
                "first_name": note.originator.person_subclass.first_name,
                "last_name": note.originator.person_subclass.last_name,
                "is_staff": note.originator.is_staff,
            } if note.originator else None,
            "provider": {
                "id": str(note.provider.id),
                "first_name": note.provider.first_name,
                "last_name": note.provider.last_name,
            } if note.provider else None,
            "billing_note": note.billing_note,
            "related_data": note.related_data,
            "datetime_of_service": note.datetime_of_service.isoformat() if note.datetime_of_service else None,
            "place_of_service": dict(PracticeLocationPOS.choices).get(str(note.place_of_service)),
            "encounter": str(note.encounter.id) if note.encounter else None,
            "body": enhanced_body,
        }
        return note_data
    def _enhance_body_with_commands(self, body: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Loop through the body array and enhance command entries with attributes.
        """
        enhanced_body = []
        for item in body:
            if item.get("type") == "command":
                enhanced_item = self._enhance_command_item(item)
                enhanced_body.append(enhanced_item)
            elif item.get("type") == "text" and item.get("value") != "":
                enhanced_body.append(item)
        return enhanced_body

    def _enhance_command_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """
        Enhance a command item by fetching the command and adding its attributes.
        """
        command_uuid = item.get("data", {}).get("command_uuid")
        if not command_uuid:
            return item
        try:
            command = Command.objects.get(id=command_uuid)
            enhanced_item = item.copy()
            enhanced_item["data"] = enhanced_item.get("data", {}).copy()
            enhanced_item["data"]["attributes"] = self._extract_command_attributes(command)
            return enhanced_item
        except Command.DoesNotExist:
            log.warning(f"Command not found: {command_uuid}")
            return item


    def _extract_command_attributes(self, command: Command) -> dict[str, Any]:
        """
        Extract relevant attributes from a command based on its schema_key.
        """
        attributes = {
            "schema_key": command.schema_key,
            "state": command.state,
            "created": command.created.isoformat() if command.created else None,
            "modified": command.modified.isoformat() if command.modified else None,
            "originator": {
                "id": str(command.originator.person_subclass.id),
                "first_name": command.originator.person_subclass.first_name,
                "last_name": command.originator.person_subclass.last_name,
                "is_staff": command.originator.is_staff,
            } if command.originator else None,
            "committer": {
                "id": str(command.committer.person_subclass.id),
                "first_name": command.committer.person_subclass.first_name,
                "last_name": command.committer.person_subclass.last_name,
                "is_staff": command.committer.is_staff,
            } if command.committer else None,
            "entered_in_error_by": {
                "id": str(command.entered_in_error_by.person_subclass.id),
                "first_name": command.entered_in_error_by.person_subclass.first_name,
                "last_name": command.entered_in_error_by.person_subclass.last_name,
                "is_staff": command.entered_in_error_by.is_staff,
            } if command.entered_in_error_by else None,
            "origination_source": command.origination_source,
        }
        if command.data:
            attributes["data"] = command.data

        return attributes
