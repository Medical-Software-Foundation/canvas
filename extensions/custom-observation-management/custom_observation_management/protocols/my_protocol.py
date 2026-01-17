from http import HTTPStatus
from typing import Any
import json, arrow, datetime
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPI, api
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.effects.observation import Observation as ObservationEffect
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.note import Note
from django.db.models import Q
from logger import log


class ObservationAPI(APIKeyAuthMixin, SimpleAPI):

    def _map_coding_to_dict(self, codings) -> dict[str, Any]:
        return [{
            "system": coding.system,
            "code": coding.code,
            "display": coding.display,
            "version": coding.version,
            "user_selected": coding.user_selected
        } for coding in codings.all()]

    def _map_observation_to_dict(self, observation: Observation) -> dict[str, Any]:

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

    @api.get(f"/observation/<observation_id>")
    def get_observation(self) -> list[Response | Effect]:

        observation_id = self.request.path_params.get("observation_id")
        if not observation_id:
            return [
                JSONResponse({"error": "Observation ID is required"}, status_code=HTTPStatus.BAD_REQUEST)
            ]

        log.info(f"Getting observation {observation_id}")
        observation = Observation.objects.get(id=observation_id)
        if not observation:
            return [
                JSONResponse({"error": "Observation not found"}, status_code=HTTPStatus.NOT_FOUND)
            ]

        log.info(f"Observation: {observation}")
        log.info(f"Observation components: {observation.components}")
        log.info(f"Observation codings: {observation.codings.all()}")
        observation_values = self._map_observation_to_dict(observation)
        log.info(f"Observation values: {observation_values}")
        return [JSONResponse(observation_values, status_code=HTTPStatus.OK)]

    @api.get(f"/observations")
    def get_observations_for_patient(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        note_dbid = self.request.query_params.get("note_dbid")
        note_uuid = self.request.query_params.get("note_uuid")
        name = self.request.query_params.get("name")
        category = self.request.query_params.get("category")

        filters = []
        if patient_id:
            if not Patient.objects.filter(id=patient_id).exists():
                return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]
            filters.append(Q(patient_id=patient_id))

        if note_dbid:
            try:
                if not Note.objects.filter(dbid=note_dbid).exists():
                    return [JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND)]
                filters.append(Q(note_id=note_dbid))
            except Exception as e:
                return [JSONResponse({"error": "Invalid note_dbid"}, status_code=HTTPStatus.BAD_REQUEST)]

        if note_uuid:
            try:
                note_id_found = Note.objects.filter(id=note_uuid).values("dbid").first()
                if note_id_found:
                    filters.append(Q(note_id=note_id_found["dbid"]))
                else:
                    return [JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND)]
            except Exception as e:
                return [JSONResponse({"error": "Invalid note_uuid"}, status_code=HTTPStatus.BAD_REQUEST)]

        if name:
            filters.append(Q(name=name))
        if category:
            filters.append(Q(category__in=category.split(",")))

        observations = Observation.objects.filter(*filters)
        return [JSONResponse([self._map_observation_to_dict(observation) for observation in observations], status_code=HTTPStatus.OK)]

    @api.post(f"/observation")
    def create_observation(self) -> list[Response | Effect]:
        try:
            data = self.request.json()
            log.info(f"Creating observation: {data}")

            errors = []

            patient_id = data.get("patient_id")
            if not patient_id:
                errors.append("'patient_id' is required")
            if patient_id and not Patient.objects.filter(id=patient_id).exists():
                errors.append("Patient not found")

            name = data.get("name")
            if not name:
                errors.append("'name' is required")

            effective_datetime = data.get("effective_datetime")
            if not effective_datetime:
                errors.append("'effective_datetime' is required")
            else:
                try:
                    effective_datetime = arrow.get(effective_datetime).datetime
                except Exception as e:
                    errors.append("Invalid effective datetime")

            if errors:
                return [JSONResponse({"errors": errors}, status_code=HTTPStatus.BAD_REQUEST)]

            effect = ObservationEffect(
                patient_id=patient_id,
                name=name,
                effective_datetime=effective_datetime,
            ).create()
            return [effect, JSONResponse({"message": "Observation created"}, status_code=HTTPStatus.CREATED)]
        except Exception as e:
            log.error(f"Error creating observation: {e}")
            return [JSONResponse({"error": str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]