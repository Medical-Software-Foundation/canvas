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
        """Convert FHIR coding objects to a list of dictionaries."""
        return [{
            "system": coding.system,
            "code": coding.code,
            "display": coding.display,
            "version": coding.version,
            "user_selected": coding.user_selected
        } for coding in codings.all()]

    def _map_observation_to_dict(self, observation: Observation) -> dict[str, Any]:
        """Convert an Observation model instance to a JSON-serializable dictionary."""
        note = Note.objects.filter(dbid=observation.note_id).values("id", "datetime_of_service").first()

        # Get codings for potential fallbacks
        codings_list = self._map_coding_to_dict(observation.codings)
        value_codings_list = self._map_coding_to_dict(observation.value_codings)

        # Name fallback: use codings[0].display if name is blank/null
        name = observation.name
        if not name and codings_list:
            name = codings_list[0].get("display", "")

        # Value fallback: use comma-separated value_coding.display if value is blank/null
        value = observation.value
        if not value and value_codings_list:
            value = ", ".join(vc.get("display", "") for vc in value_codings_list if vc.get("display"))

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
            "value": value,
            "note": {
                "id": str(note["id"]),
                "dbid": observation.note_id,
                "datetime_of_service": note["datetime_of_service"].isoformat() if note["datetime_of_service"] else None,
            } if note else None,
            "note_id": str(observation.note_id),
            "name": name,
            "effective_datetime": observation.effective_datetime.isoformat() if observation.effective_datetime else None,
            "codings": codings_list,
            "components": [
                {
                    "name": component.name,
                    "value": component.value_quantity,
                    "unit": component.value_quantity_unit,
                    "codings": self._map_coding_to_dict(component.codings),
                } for component in observation.components.all()
            ],
            "value_codings": value_codings_list,
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

    def _build_observation_filters(self) -> tuple[list[Q], list[Response] | None]:
        """
        Build filter list from query parameters.

        Returns:
            Tuple of (list of Q filters, error response or None).
        """
        patient_id = self.request.query_params.get("patient_id")
        note_dbid = self.request.query_params.get("note_dbid")
        note_uuid = self.request.query_params.get("note_uuid")
        name = self.request.query_params.get("name")
        category = self.request.query_params.get("category")
        effective_datetime_start = self.request.query_params.get("effective_datetime_start")
        effective_datetime_end = self.request.query_params.get("effective_datetime_end")

        filters = []

        # Patient filter
        if patient_id:
            if not Patient.objects.filter(id=patient_id).exists():
                return [], [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]
            filters.append(Q(patient__id=patient_id))

        # Note filter by database ID
        if note_dbid:
            try:
                if not Note.objects.filter(dbid=note_dbid).exists():
                    return [], [JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND)]
                filters.append(Q(note_id=note_dbid))
            except Exception:
                return [], [JSONResponse({"error": "Invalid note_dbid"}, status_code=HTTPStatus.BAD_REQUEST)]

        # Note filter by UUID
        if note_uuid:
            try:
                note_id_found = Note.objects.filter(id=note_uuid).values("dbid").first()
                if note_id_found:
                    filters.append(Q(note_id=note_id_found["dbid"]))
                else:
                    return [], [JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND)]
            except Exception:
                return [], [JSONResponse({"error": "Invalid note_uuid"}, status_code=HTTPStatus.BAD_REQUEST)]

        # Name filter - supports || separated values (not comma, as names may contain commas)
        # Also matches codings[0].display when name is blank (fallback logic)
        if name:
            names = [n.strip() for n in name.split("||") if n.strip()]
            if names:
                filters.append(
                    Q(name__in=names) |
                    (Q(name__isnull=True) | Q(name="")) & Q(codings__display__in=names)
                )

        # Category filter - supports || separated values
        if category:
            categories = [c.strip() for c in category.split("||") if c.strip()]
            if categories:
                filters.append(Q(category__in=categories))

        # Datetime range filter - start
        if effective_datetime_start:
            try:
                arrow.get(effective_datetime_start)
                filters.append(Q(effective_datetime__gte=effective_datetime_start))
            except Exception:
                return [], [JSONResponse(
                    {"error": "Invalid effective_datetime_start format. Use ISO 8601 format."},
                    status_code=HTTPStatus.BAD_REQUEST
                )]

        # Datetime range filter - end
        if effective_datetime_end:
            try:
                arrow.get(effective_datetime_end)
                filters.append(Q(effective_datetime__lte=effective_datetime_end))
            except Exception:
                return [], [JSONResponse(
                    {"error": "Invalid effective_datetime_end format. Use ISO 8601 format."},
                    status_code=HTTPStatus.BAD_REQUEST
                )]

        return filters, None

    def _apply_pagination(self, items: list, page: int, page_size: int) -> tuple[list, int, int]:
        """Apply pagination to a list of items."""
        total_count = len(items)
        total_pages = max(1, (total_count + page_size - 1) // page_size)

        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages

        offset = (page - 1) * page_size
        paginated_items = items[offset:offset + page_size]

        return paginated_items, total_count, total_pages

    def _get_sort_value(self, obs_dict: dict, sort_by: str) -> Any:
        """Get the value to sort by for an observation dict."""
        if sort_by == "date":
            # Use effective_datetime, fall back to note.datetime_of_service
            date_val = obs_dict.get("effective_datetime")
            if not date_val and obs_dict.get("note"):
                date_val = obs_dict["note"].get("datetime_of_service")
            return date_val or ""
        elif sort_by == "name":
            return (obs_dict.get("name") or "").lower()
        elif sort_by == "value":
            # Try to sort numerically if possible, otherwise alphabetically
            val = obs_dict.get("value") or ""
            try:
                return (0, float(val))  # Numeric values sort first
            except (ValueError, TypeError):
                return (1, val.lower())  # Non-numeric values sort after
        elif sort_by == "units":
            return (obs_dict.get("units") or "").lower()
        elif sort_by == "category":
            return (obs_dict.get("category") or "").lower()
        return ""

    @api.get("/observations")
    def get_observations_for_patient(self) -> list[Response | Effect]:
        """
        Retrieve observations with optional filtering, sorting, and pagination.

        Excludes deleted observations and those marked as entered-in-error.
        Groups member observations under their parent observations.

        Query Parameters:
            patient_id (str, optional): Filter by patient UUID. Returns 404 if patient not found.
            note_dbid (str, optional): Filter by note database ID. Returns 404 if note not found.
            note_uuid (str, optional): Filter by note UUID. Internally converts to dbid.
            name (str, optional): Filter by observation name. Supports comma-separated values.
            category (str, optional): Filter by category. Supports comma-separated values.
            effective_datetime_start (str, optional): Filter by start date (ISO 8601).
            effective_datetime_end (str, optional): Filter by end date (ISO 8601).
            sort_by (str, optional): Column to sort by (date, name, value, units, category). Default: date.
            sort_order (str, optional): Sort order (asc, desc). Default: desc.
            ungrouped (str, optional): If "true", return flat list without parent-child grouping. Default: false.
            page (int, optional): Page number (default: 1).
            page_size (int, optional): Items per page (default: 25, max: 100).

        Returns:
            200 OK: JSON object with observations array and pagination metadata.
                    Member observations are nested under their parent's "members" field (unless ungrouped=true).
            400 Bad Request: If datetime format is invalid.
            404 Not Found: If specified patient or note doesn't exist.
        """
        filters, error_response = self._build_observation_filters()
        if error_response:
            return error_response

        # Pagination parameters
        try:
            page = int(self.request.query_params.get("page", 1))
            page_size = min(int(self.request.query_params.get("page_size", 25)), 100)
        except ValueError:
            page = 1
            page_size = 25

        # Sorting parameters
        sort_by = self.request.query_params.get("sort_by", "date")
        sort_order = self.request.query_params.get("sort_order", "desc")
        if sort_by not in ("date", "name", "value", "units", "category"):
            sort_by = "date"
        if sort_order not in ("asc", "desc"):
            sort_order = "desc"

        # Grouping parameter
        ungrouped = self.request.query_params.get("ungrouped", "false").lower() == "true"

        # Query all observations matching filters (excluding deleted/error)
        base_queryset = Observation.objects.exclude(
            deleted=True
        ).exclude(
            entered_in_error_id__isnull=False
        ).exclude(
            name__in=['bmi_percentile', 'weight_for_length_percentile']
        )
        matching_observations = base_queryset.filter(*filters)

        if ungrouped:
            # Return flat list of all matching observations (no grouping)
            observations_list = []
            for obs in matching_observations:
                obs_dict = self._map_observation_to_dict(obs)
                obs_dict["members"] = []  # No members in ungrouped mode
                observations_list.append(obs_dict)

            # Exclude observations that have no value
            observations_list = [
                obs for obs in observations_list
                if obs.get("value")
            ]
        else:
            # Find parent IDs for any matching member observations
            parent_ids = set(
                matching_observations
                .exclude(is_member_of__isnull=True)
                .values_list("is_member_of__id", flat=True)
            )

            # Combine: top-level observations that match filters + parents of matching members
            top_level_ids = set(
                matching_observations
                .filter(is_member_of__isnull=True)
                .values_list("id", flat=True)
            )
            all_parent_ids = top_level_ids | parent_ids

            # Get the final list of parent/top-level observations
            final_parents = (
                base_queryset
                .filter(id__in=all_parent_ids)
                .order_by("-effective_datetime")
            )

            # Build a map of parent_id -> list of MATCHING member observations only
            # Only include members that match the filter criteria
            member_map: dict[str, list[dict]] = {}
            matching_member_observations = matching_observations.exclude(is_member_of__isnull=True)

            for member in matching_member_observations:
                parent_id = str(member.is_member_of.id)
                if parent_id not in member_map:
                    member_map[parent_id] = []
                member_map[parent_id].append(self._map_observation_to_dict(member))

            # Convert parent observations to dicts and attach only matching members
            observations_list = []
            for obs in final_parents:
                obs_dict = self._map_observation_to_dict(obs)
                obs_dict["members"] = member_map.get(str(obs.id), [])
                observations_list.append(obs_dict)

            # Exclude observations that have no value and no members
            observations_list = [
                obs for obs in observations_list
                if obs.get("value") or obs.get("members")
            ]

        # Apply sorting
        reverse_sort = sort_order == "desc"
        observations_list.sort(
            key=lambda obs: self._get_sort_value(obs, sort_by),
            reverse=reverse_sort
        )

        # Apply pagination to parent observations
        paginated_observations, total_count, total_pages = self._apply_pagination(
            observations_list, page, page_size
        )

        return [JSONResponse({
            "observations": paginated_observations,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "page_size": page_size,
                "has_previous": page > 1,
                "has_next": page < total_pages,
            }
        }, status_code=HTTPStatus.OK)]

    def _get_effective_name(self, observation: Observation) -> str:
        """Get the effective name for an observation, using codings fallback if needed."""
        if observation.name:
            return observation.name
        # Fallback to codings[0].display
        first_coding = observation.codings.first()
        if first_coding and first_coding.display:
            return first_coding.display
        return ""

    @api.get("/observation-filters")
    def get_observation_filters(self) -> list[Response | Effect]:
        """
        Get unique observation names and categories for filter dropdowns.

        Uses the same name fallback logic as observations list:
        if name is blank/null, uses codings[0].display.

        Query Parameters:
            patient_id (str, optional): Filter by patient UUID.

        Returns:
            200 OK: JSON object with names and categories arrays.
        """
        patient_id = self.request.query_params.get("patient_id")

        queryset = Observation.objects.exclude(deleted=True, entered_in_error_id__isnull=False)

        if patient_id:
            if not Patient.objects.filter(id=patient_id).exists():
                return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]
            queryset = queryset.filter(patient__id=patient_id)

        # Get unique names using fallback logic (name or codings[0].display)
        names_set = set()
        for obs in queryset.prefetch_related("codings"):
            effective_name = self._get_effective_name(obs)
            if effective_name:
                names_set.add(effective_name)
        names = sorted(names_set)

        categories = list(
            queryset
            .exclude(category__isnull=True)
            .exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )

        return [JSONResponse({"names": names, "categories": categories}, status_code=HTTPStatus.OK)]

    def _parse_codings(self, codings_data: list[dict] | None, field_name: str) -> tuple[list[CodingData] | None, list[str]]:
        """
        Parse and validate a list of coding dictionaries into CodingData objects.

        Args:
            codings_data: List of coding dictionaries from request body.
            field_name: Name of the field being parsed (for error messages).

        Returns:
            Tuple of (list of CodingData objects or None, list of error messages).
        """
        errors = []
        if codings_data is None:
            return None, errors

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
        errors = []
        if components_data is None:
            return None, errors

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
                "patient_id": "762d7d3530b645a3b1edd4fbcdbf2192",
                "name": "Blood Pressure",
                "effective_datetime": "2024-06-15T10:30:00Z"
            }

        Example Request (full):
            POST /observation
            {
                "patient_id": "762d7d3530b645a3b1edd4fbcdbf2192",
                "name": "Blood Pressure",
                "effective_datetime": "2024-06-15T10:30:00Z",
                "category": "vital-signs",
                "value": "120/80",
                "units": "mmHg",
                "note_id": 12345,
                "is_member_of_id": "parent-observation-uuid",
                "codings": [
                    {
                        "system": "http://loinc.org",
                        "code": "85354-9",
                        "display": "Blood pressure panel",
                        "version": "2.74",
                        "user_selected": true
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
                ],
                "value_codings": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "266079004",
                        "display": "Normal blood pressure"
                    }
                ]
            }
        """
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

        return [effect, JSONResponse({"message": "Observation successfully sent to Canvas"}, status_code=HTTPStatus.CREATED)]
