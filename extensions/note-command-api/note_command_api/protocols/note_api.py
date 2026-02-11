from http import HTTPStatus
from typing import Any

import arrow
import uuid
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPIRoute
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.practicelocation import PracticeLocationPOS
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from logger import log
from django.db.models import Q


class CreateNoteAPI(APIKeyAuthMixin, SimpleAPIRoute):
    """
    SimpleAPI endpoint for creating notes.

    POST /create-note - Creates a new note.

    Request body:
        {
            "instance_id": "uuid (optional) - If not provided, a new UUID will be generated",

            # Note type - ONE of the following is required:
            "note_type_id": "uuid - Must reference an existing active NoteType",
            "note_type_name": "string - Name of an existing active NoteType",
            "note_type_code": "string - Code of an existing active NoteType",

            "datetime_of_service": "datetime string (required) - e.g. '2025-02-21 23:31:42'",

            "patient_id": "uuid (required) - Must reference an existing Patient",

            # Practice location - ONE of the following is required:
            "practice_location_id": "uuid - Must reference an existing active PracticeLocation",
            "practice_location_name": "string - Full name or short name of an active PracticeLocation",

            # Provider - ONE of the following is required:
            "provider_id": "uuid - Must reference an existing active Staff member",
            "provider_name": "string - Full name (first + last) of an active Staff member",

            "title": "string (optional) - Custom title for the note"
        }

    Response:
        - 202 Accepted: Note creation accepted with {"message": "...", "note_id": "..."}
        - 400 Bad Request: Validation errors (missing required fields, invalid UUIDs,
          entity not found, note already exists, etc.)

    Authentication:
        Requires API key authentication via the 'simpleapi-api-key' secret.
    """

    PATH = "/create-note"

    def get_practice_location_identifier(self, request_body: dict[str, Any]) -> str:
        """
        Get the practice location identifier from the request body.
        """
        if practice_location_name := request_body.get("practice_location_name"):
            return PracticeLocation.objects.filter(Q(full_name=practice_location_name) | Q(short_name=practice_location_name), active=True).values_list('id', flat=True).first()
        elif practice_location_id := request_body.get("practice_location_id"):
            return PracticeLocation.objects.filter(id=practice_location_id, active=True).values_list('id', flat=True).first()
        return None

    def get_provider_identifier(self, request_body: dict[str, Any]) -> str:
        """
        Get the provider identifier from the request body.
        """
        if provider_name := request_body.get("provider_name"):
            for provider in Staff.objects.filter(active=True).values('id', 'first_name', 'last_name'):
                if f"{provider['first_name']} {provider['last_name']}".strip() == provider_name.strip():
                    return provider['id']
        elif provider_id := request_body.get("provider_id"):
            return Staff.objects.filter(id=provider_id, active=True).values_list('id', flat=True).first()
        return None

    def get_note_type_identifier(self, request_body: dict[str, Any]) -> str:
        """
        Get the note type identifier from the request body.
        """
        if note_type_name := request_body.get("note_type_name"):
            return NoteType.objects.filter(name=note_type_name, is_active=True).values_list('id', flat=True).first()
        elif note_type_code := request_body.get("note_type_code"):
            return NoteType.objects.filter(code=note_type_code, is_active=True).values_list('id', flat=True).first()
        elif note_type_id := request_body.get("note_type_id"):
            return NoteType.objects.filter(id=note_type_id, is_active=True).values_list('id', flat=True).first()
        return None

    def post(self) -> list[Response | Effect]:
        """Create a new note with validation of all referenced entities."""
        required_attributes = {
            ("note_type_id", "note_type_name", "note_type_code"),
            ("datetime_of_service",),
            ("patient_id",),
            ("practice_location_id", "practice_location_name"),
            ("provider_id", "provider_name"),
        }
        errors = []
        request_body = self.request.json()
        for attribute_tuple in required_attributes:
            # at least one of the attributes in the tuple must be present in the request body
            if not any(request_body.get(attribute) for attribute in attribute_tuple):
                errors.append(f"Missing required attribute(s): {', '.join(attribute_tuple)}")
        
        if errors:
            return [
                JSONResponse(
                    {"errors": errors},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # validate uuid strings
        uuid_attributes = ["instance_id", "note_type_id", "patient_id", "practice_location_id", "provider_id"]
        for attribute_name in uuid_attributes:
            if attribute := request_body.get(attribute_name):
                try:
                    uuid.UUID(attribute)
                except ValueError:
                    errors.append(f"Invalid {attribute_name}, must be a valid UUID string but got {attribute}")

        if errors:
            return [
                JSONResponse(
                    {"errors": errors},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(f"Request body: {request_body}")

        if instance_id := request_body.get("instance_id"):
            if Note.objects.filter(id=instance_id).exists():
                errors.append("Note already exists")
        else:
            instance_id = str(uuid.uuid4())

        # get note type
        note_type_identifier = self.get_note_type_identifier(request_body)
        if not note_type_identifier:
            errors.append("Note type not found")
        
        try:
            datetime_of_service = arrow.get(request_body["datetime_of_service"]).datetime
        except ValueError:
            errors.append("Invalid datetime_of_service, must be a valid datetime string")

        patient_id = request_body["patient_id"]
        if not Patient.objects.filter(id=patient_id).exists():
            errors.append("Patient not found")
        
        practice_location_identifier = self.get_practice_location_identifier(request_body)
        if not practice_location_identifier:
            errors.append("Practice location not found")

        provider_identifier = self.get_provider_identifier(request_body)
        if not provider_identifier:
            errors.append("Provider not found")

        title = str(request_body.get("title"))

        if errors:
            return [
                JSONResponse(
                    {"errors": errors},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        note_effect = NoteEffect(
            instance_id=instance_id,
            note_type_id=note_type_identifier,
            datetime_of_service=datetime_of_service,
            patient_id=patient_id,
            practice_location_id=practice_location_identifier,
            provider_id=provider_identifier,
            title=title,
        )

        return [
            note_effect.create(),
            JSONResponse(
                {"message": "Note creation accepted",
                 "note_id": instance_id},
                status_code=HTTPStatus.ACCEPTED,
            ),
        ]

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
