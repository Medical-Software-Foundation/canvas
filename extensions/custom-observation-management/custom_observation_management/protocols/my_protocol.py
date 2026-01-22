"""
Observation Management API

A SimpleAPI-based HTTP handler for managing patient observations in Canvas.
Provides endpoints for retrieving and creating observations with various
filtering options including date range queries.

Authentication: API Key (via APIKeyAuthMixin)
Required secret: simpleapi-api-key
"""

from http import HTTPStatus
from typing import Any

import arrow
from django.db.models import Q

from canvas_sdk.effects import Effect
from canvas_sdk.effects.observation import CodingData, Observation as ObservationEffect, ObservationComponentData
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPI, api
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.patient import Patient
from logger import log


class ObservationAPI(APIKeyAuthMixin, SimpleAPI):
    """
    API handler for observation management operations.

    Endpoints:
        GET /observation/<observation_id> - Retrieve a single observation by ID
        GET /observations - List/filter observations with query parameters
        POST /observation - Create a new observation

    Authentication:
        Requires API key authentication via the 'simpleapi-api-key' secret.
    """

    def _map_coding_to_dict(self, codings) -> list[dict[str, Any]]:
        """
        Convert FHIR coding objects to a list of dictionaries.

        Args:
            codings: A Django queryset or manager of coding objects.

        Returns:
            List of dictionaries containing coding information with keys:
            - system: The coding system URI
            - code: The code value
            - display: Human-readable display text
            - version: The version of the coding system
            - user_selected: Whether the coding was selected by a user
        """
        return [{
            "system": coding.system,
            "code": coding.code,
            "display": coding.display,
            "version": coding.version,
            "user_selected": coding.user_selected
        } for coding in codings.all()]

    def _map_observation_to_dict(self, observation: Observation) -> dict[str, Any]:
        """
        Convert an Observation model instance to a JSON-serializable dictionary.

        Args:
            observation: The Observation model instance to convert.

        Returns:
            Dictionary containing all observation fields including:
            - id: Observation UUID
            - patient: Patient info (id, first_name, last_name) or None
            - is_member_of: Organization membership info or None
            - category: Observation category
            - units: Measurement units
            - value: Observation value
            - note: Associated note info (id, dbid, datetime_of_service) or None
            - note_id: Note database ID as string
            - name: Observation name
            - effective_datetime: ISO formatted datetime or None
            - codings: List of FHIR codings
            - components: List of observation components with their codings
            - value_codings: List of value codings
        """
        # Fetch associated note information
        note = Note.objects.filter(dbid=observation.note_id).values("id", "datetime_of_service").first()

        return {
            "id": str(observation.id),
            "patient": {
                "id": str(observation.patient.id),
                "first_name": observation.patient.first_name,
                "last_name": observation.patient.last_name,
            } if observation.patient else None,
            "is_member_of": {
                "id": str(observation.is_member_of.id),
                "name": observation.is_member_of.name,
            } if observation.is_member_of else None,
            "category": observation.category,
            "units": observation.units,
            "value": observation.value,
            "note": {
                "id": str(note["id"]),
                "dbid": observation.note_id,
                "datetime_of_service": note["datetime_of_service"].isoformat() if note["datetime_of_service"] else None,
            } if note else None,
            "note_id": str(observation.note_id),
            "name": observation.name,
            "effective_datetime": observation.effective_datetime.isoformat() if observation.effective_datetime else None,
            "codings": self._map_coding_to_dict(observation.codings),
            "components": [
                {
                    "name": component.name,
                    "value": component.value_quantity,
                    "unit": component.value_quantity_unit,
                    "codings": self._map_coding_to_dict(component.codings),
                } for component in observation.components.all()
            ],
            "value_codings": self._map_coding_to_dict(observation.value_codings),
        }

    @api.get("/observation/<observation_id>")
    def get_observation(self) -> list[Response | Effect]:
        """
        Retrieve a single observation by its UUID.

        Path Parameters:
            observation_id: The UUID of the observation to retrieve.

        Returns:
            200 OK: JSON object containing the observation data.
            400 Bad Request: If observation_id is missing.
            404 Not Found: If observation doesn't exist.
        """
        observation_id = self.request.path_params.get("observation_id")
        if not observation_id:
            return [
                JSONResponse({"error": "Observation ID is required"}, status_code=HTTPStatus.BAD_REQUEST)
            ]

        observation = Observation.objects.get(id=observation_id)
        if not observation:
            return [
                JSONResponse({"error": "Observation not found"}, status_code=HTTPStatus.NOT_FOUND)
            ]

        observation_values = self._map_observation_to_dict(observation)
        return [JSONResponse(observation_values, status_code=HTTPStatus.OK)]

    @api.get("/observations")
    def get_observations_for_patient(self) -> list[Response | Effect]:
        """
        Retrieve observations with optional filtering.

        Excludes deleted observations and those marked as entered-in-error.

        Query Parameters:
            patient_id (str, optional): Filter by patient UUID. Returns 404 if patient not found.
            note_dbid (str, optional): Filter by note database ID. Returns 404 if note not found.
            note_uuid (str, optional): Filter by note UUID. Internally converts to dbid.
            name (str, optional): Filter by exact observation name match.
            category (str, optional): Filter by category. Supports comma-separated values
                for multiple categories (e.g., "vital-signs,laboratory").
            effective_datetime_start (str, optional): Filter observations with effective_datetime
                on or after this value. Must be ISO 8601 format (e.g., "2024-01-01T00:00:00Z").
            effective_datetime_end (str, optional): Filter observations with effective_datetime
                on or before this value. Must be ISO 8601 format (e.g., "2024-12-31T23:59:59Z").

        Returns:
            200 OK: JSON array of observation objects matching the filters.
            400 Bad Request: If datetime format is invalid or note_dbid/note_uuid is malformed.
            404 Not Found: If specified patient or note doesn't exist.

        Examples:
            GET /observations?patient_id=abc-123
            GET /observations?name=Blood%20Pressure&category=vital-signs
            GET /observations?effective_datetime_start=2024-01-01T00:00:00Z&effective_datetime_end=2024-12-31T23:59:59Z
        """
        # Extract query parameters
        patient_id = self.request.query_params.get("patient_id")
        note_dbid = self.request.query_params.get("note_dbid")
        note_uuid = self.request.query_params.get("note_uuid")
        name = self.request.query_params.get("name")
        category = self.request.query_params.get("category")
        effective_datetime_start = self.request.query_params.get("effective_datetime_start")
        effective_datetime_end = self.request.query_params.get("effective_datetime_end")

        # Build filter list using Q objects for flexible querying
        filters = []

        # Patient filter - validate patient exists before filtering
        if patient_id:
            if not Patient.objects.filter(id=patient_id).exists():
                return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]
            filters.append(Q(patient__id=patient_id))

        # Note filter by database ID
        if note_dbid:
            try:
                if not Note.objects.filter(dbid=note_dbid).exists():
                    return [JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND)]
                filters.append(Q(note_id=note_dbid))
            except Exception:
                return [JSONResponse({"error": "Invalid note_dbid"}, status_code=HTTPStatus.BAD_REQUEST)]

        # Note filter by UUID - convert to dbid for filtering
        if note_uuid:
            try:
                note_id_found = Note.objects.filter(id=note_uuid).values("dbid").first()
                if note_id_found:
                    filters.append(Q(note_id=note_id_found["dbid"]))
                else:
                    return [JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND)]
            except Exception:
                return [JSONResponse({"error": "Invalid note_uuid"}, status_code=HTTPStatus.BAD_REQUEST)]

        # Name filter - exact match
        if name:
            filters.append(Q(name=name))

        # Category filter - supports comma-separated values for multiple categories
        if category:
            filters.append(Q(category__in=category.split(",")))

        # Datetime range filter - start (inclusive)
        if effective_datetime_start:
            try:
                arrow.get(effective_datetime_start)  # Validate datetime format
                filters.append(Q(effective_datetime__gte=effective_datetime_start))
            except Exception:
                return [JSONResponse(
                    {"error": "Invalid effective_datetime_start format. Use ISO 8601 format."},
                    status_code=HTTPStatus.BAD_REQUEST
                )]

        # Datetime range filter - end (inclusive)
        if effective_datetime_end:
            try:
                arrow.get(effective_datetime_end)  # Validate datetime format
                filters.append(Q(effective_datetime__lte=effective_datetime_end))
            except Exception:
                return [JSONResponse(
                    {"error": "Invalid effective_datetime_end format. Use ISO 8601 format."},
                    status_code=HTTPStatus.BAD_REQUEST
                )]

        # Query observations, excluding deleted and entered-in-error records
        observations = Observation.objects.exclude(deleted=True, entered_in_error_id__isnull=False).filter(*filters)
        return [JSONResponse([self._map_observation_to_dict(observation) for observation in observations], status_code=HTTPStatus.OK)]

    def _parse_codings(self, codings_data: list[dict] | None, field_name: str) -> tuple[list[CodingData] | None, list[str]]:
        """
        Parse and validate a list of coding dictionaries into CodingData objects.

        Args:
            codings_data: List of coding dictionaries from request body.
            field_name: Name of the field being parsed (for error messages).

        Returns:
            Tuple of (list of CodingData objects or None, list of error messages).
        """
        if codings_data is None:
            return None, []

        errors = []
        if not isinstance(codings_data, list):
            return None, [f"'{field_name}' must be a list"]

        codings = []
        for i, coding_dict in enumerate(codings_data):
            if not isinstance(coding_dict, dict):
                errors.append(f"'{field_name}[{i}]' must be an object")
                continue

            # Required fields for CodingData
            code = coding_dict.get("code")
            display = coding_dict.get("display")
            system = coding_dict.get("system")

            if not code:
                errors.append(f"'{field_name}[{i}].code' is required")
            if not display:
                errors.append(f"'{field_name}[{i}].display' is required")
            if not system:
                errors.append(f"'{field_name}[{i}].system' is required")

            if code and display and system:
                codings.append(CodingData(
                    code=code,
                    display=display,
                    system=system,
                    version=coding_dict.get("version", ""),
                    user_selected=coding_dict.get("user_selected", False),
                ))

        return codings if codings else None, errors

    def _parse_components(self, components_data: list[dict] | None) -> tuple[list[ObservationComponentData] | None, list[str]]:
        """
        Parse and validate a list of component dictionaries into ObservationComponentData objects.

        Args:
            components_data: List of component dictionaries from request body.

        Returns:
            Tuple of (list of ObservationComponentData objects or None, list of error messages).
        """
        if components_data is None:
            return None, []

        errors = []
        if not isinstance(components_data, list):
            return None, ["'components' must be a list"]

        components = []
        for i, comp_dict in enumerate(components_data):
            if not isinstance(comp_dict, dict):
                errors.append(f"'components[{i}]' must be an object")
                continue

            # Required fields for ObservationComponentData
            value_quantity = comp_dict.get("value_quantity")
            value_quantity_unit = comp_dict.get("value_quantity_unit")
            name = comp_dict.get("name")

            if not value_quantity:
                errors.append(f"'components[{i}].value_quantity' is required")
            if not value_quantity_unit:
                errors.append(f"'components[{i}].value_quantity_unit' is required")
            if not name:
                errors.append(f"'components[{i}].name' is required")

            # Parse component codings if present
            component_codings, coding_errors = self._parse_codings(
                comp_dict.get("codings"),
                f"components[{i}].codings"
            )
            errors.extend(coding_errors)

            if value_quantity and value_quantity_unit and name:
                components.append(ObservationComponentData(
                    value_quantity=value_quantity,
                    value_quantity_unit=value_quantity_unit,
                    name=name,
                    codings=component_codings,
                ))

        return components if components else None, errors

    @api.post("/observation")
    def create_observation(self) -> list[Response | Effect]:
        """
        Create a new observation for a patient.

        Request Body (JSON):
            Required Fields:
                patient_id (str): The UUID of the patient.
                name (str): The name/type of the observation (e.g., "Blood Pressure").
                effective_datetime (str): When the observation was taken.
                    Must be ISO 8601 format (e.g., "2024-06-15T10:30:00Z").

            Optional Fields:
                category (str | list[str]): Observation category (e.g., "vital-signs").
                value (str): The observation value (e.g., "120/80").
                units (str): Units of measurement (e.g., "mmHg").
                note_id (int): Database ID of the associated note. Cannot be used with note_uuid.
                note_uuid (str): UUID of the associated note. Cannot be used with note_id.
                is_member_of_id (str): UUID of parent observation (for grouped observations).
                codings (list[object]): FHIR codings for the observation.
                    Each coding object requires: code, display, system.
                    Optional: version, user_selected.
                components (list[object]): Observation components (e.g., systolic/diastolic).
                    Each component requires: name, value_quantity, value_quantity_unit.
                    Optional: codings (list of coding objects).
                value_codings (list[object]): FHIR codings for the observation value.
                    Same structure as codings.

        Returns:
            201 Created: Observation created successfully. Returns the ObservationEffect
                and a JSON response with success message.
            400 Bad Request: If required fields are missing, patient not found,
                validation fails, or datetime format is invalid. Returns list of errors.
            500 Internal Server Error: If an unexpected error occurs.

        Example Request (minimal):
            POST /observation
            {
                "patient_id": "abc-123-def",
                "name": "Blood Pressure",
                "effective_datetime": "2024-06-15T10:30:00Z"
            }

        Example Request (full):
            POST /observation
            {
                "patient_id": "abc-123-def",
                "name": "Blood Pressure",
                "effective_datetime": "2024-06-15T10:30:00Z",
                "category": "vital-signs",
                "value": "120/80",
                "units": "mmHg",
                "codings": [
                    {
                        "system": "http://loinc.org",
                        "code": "85354-9",
                        "display": "Blood pressure panel"
                    }
                ],
                "components": [
                    {
                        "name": "Systolic",
                        "value_quantity": "120",
                        "value_quantity_unit": "mmHg",
                        "codings": [
                            {
                                "system": "http://loinc.org",
                                "code": "8480-6",
                                "display": "Systolic blood pressure"
                            }
                        ]
                    },
                    {
                        "name": "Diastolic",
                        "value_quantity": "80",
                        "value_quantity_unit": "mmHg",
                        "codings": [
                            {
                                "system": "http://loinc.org",
                                "code": "8462-4",
                                "display": "Diastolic blood pressure"
                            }
                        ]
                    }
                ]
            }
        """
        try:
            data = self.request.json()
            log.info(f"Creating observation: {data}")

            errors = []

            # === Required fields ===

            # Validate patient_id
            patient_id = data.get("patient_id")
            if not patient_id:
                errors.append("'patient_id' is required")
            elif not Patient.objects.filter(id=patient_id).exists():
                errors.append("Patient not found")

            # Validate name
            name = data.get("name")
            if not name:
                errors.append("'name' is required")

            # Validate and parse effective_datetime
            effective_datetime = data.get("effective_datetime")
            if not effective_datetime:
                errors.append("'effective_datetime' is required")
            else:
                try:
                    effective_datetime = arrow.get(effective_datetime).datetime
                except Exception:
                    errors.append("Invalid effective_datetime format. Use ISO 8601 format.")

            # === Optional fields ===

            # Category - can be string or list of strings
            category = data.get("category")
            if category is not None:
                if not isinstance(category, (str, list)):
                    errors.append("'category' must be a string or list of strings")
                elif isinstance(category, list) and not all(isinstance(c, str) for c in category):
                    errors.append("'category' list must contain only strings")

            # Value - string
            value = data.get("value")
            if value is not None and not isinstance(value, str):
                errors.append("'value' must be a string")

            # Units - string
            units = data.get("units")
            if units is not None and not isinstance(units, str):
                errors.append("'units' must be a string")

            # Note reference - can be note_id (int) or note_uuid (str), but not both
            note_id = data.get("note_id")
            note_uuid = data.get("note_uuid")

            if note_id is not None and note_uuid is not None:
                errors.append("Cannot specify both 'note_id' and 'note_uuid'. Use one or the other.")
            elif note_id is not None:
                if not isinstance(note_id, int):
                    errors.append("'note_id' must be an integer")
                elif not Note.objects.filter(dbid=note_id).exists():
                    errors.append("Note not found")
            elif note_uuid is not None:
                if not isinstance(note_uuid, str):
                    errors.append("'note_uuid' must be a string")
                else:
                    # Look up the note by UUID and get its dbid
                    note_record = Note.objects.filter(id=note_uuid).values("dbid").first()
                    if note_record:
                        note_id = note_record["dbid"]
                    else:
                        errors.append("Note not found")

            # Is member of ID - validate parent observation exists
            is_member_of_id = data.get("is_member_of_id")
            if is_member_of_id is not None:
                if not isinstance(is_member_of_id, str):
                    errors.append("'is_member_of_id' must be a string (UUID)")
                elif not Observation.objects.filter(id=is_member_of_id).exists():
                    errors.append("Parent observation not found")

            # Parse codings
            codings, coding_errors = self._parse_codings(data.get("codings"), "codings")
            errors.extend(coding_errors)

            # Parse components
            components, component_errors = self._parse_components(data.get("components"))
            errors.extend(component_errors)

            # Parse value_codings
            value_codings, value_coding_errors = self._parse_codings(data.get("value_codings"), "value_codings")
            errors.extend(value_coding_errors)

            # Return all validation errors at once
            if errors:
                return [JSONResponse({"errors": errors}, status_code=HTTPStatus.BAD_REQUEST)]

            # Build the observation effect with all provided fields
            effect = ObservationEffect(
                patient_id=patient_id,
                name=name,
                effective_datetime=effective_datetime,
                category=category,
                value=value,
                units=units,
                note_id=note_id,
                is_member_of_id=is_member_of_id,
                codings=codings,
                components=components,
                value_codings=value_codings,
            ).create()

            return [effect, JSONResponse({"message": "Observation created"}, status_code=HTTPStatus.CREATED)]

        except Exception as e:
            log.error(f"Error creating observation: {e}")
            return [JSONResponse({"error": str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]
