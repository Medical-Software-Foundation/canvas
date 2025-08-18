import arrow
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api, APIKeyAuthMixin
from canvas_sdk.effects.patient_metadata.base import PatientMetadata
from canvas_sdk.v1.data.patient import Patient

from patient_metadata_management.protocols.patient_metadata_fields import METADATA_VALIDATION

class ValidationError(Exception):
    pass


def validate_field(key: str | None, value: str | None) -> str:
	"""
		Given a key, value metadata pair, apply form valiation depending on the type: string, choice, date

		Raise exception if input isn't expected to return friendly error message to user
	"""

    # ignore any where the key isn't given or the value is None
    if not key or value is None:
        raise ValidationError(f"Insufficient data given: key={key}, value={value}")

    validation = METADATA_VALIDATION.get(key)

    # if key is not found, we don't have a form field for it, so we skip
    if not validation:
        raise ValidationError(f"Unsupported metadata field given: {key}")


    value = str(value)

    # if value is empty, return early no need to validate
    if not value:
    	return value

    # check that the string is given for a list of options
    if "options" in validation and value not in validation['options']:
        raise ValidationError(f"Unsupported option given for metadata {key}: {value}")

    # check the date string can be converted to a date
    if "format" in validation and value:
        try:
            value = arrow.get(value, validation['format']).date().isoformat()
        except Exception as e:
            raise ValidationError(f"Unsupported date format given for metadata {key}: {value} expecting {validation['format']}")


    return value


class MetadataAPI(APIKeyAuthMixin, SimpleAPI):

    def handle_metadata_upsert(self, patient_id: str, patient_metadata: list) -> list[Response | Effect]:
    	"""
			Function to handle: 
				1. Patient Validation
				2. Metadata key, value validation
				3. Return list of Patient Metadata upsert effects and/or a JSONResponse 
    	"""

        # check patient is on instance
        if not Patient.objects.filter(id=patient_id).exists():
            return [JSONResponse(
                {"message": f"Patient with ID {patient_id} does not exist."},
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )]


        effects = []
        for metadata in patient_metadata:
            key = metadata.get('key')
            value = metadata.get('value')

            try:
                value = validate_field(key, value)
            except ValidationError as e:
                return [JSONResponse(
                    {"message": str(e)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]

            # Upsert Metadata for patient with given key and value
            metadata_effect = PatientMetadata(
                patient_id=patient_id,
                key=key
            )
            effects.append(metadata_effect.upsert(value=value))

        return [
            *effects,
            JSONResponse(
                {"message": "Successfully sent patient metadata to Canvas.",
                 "patient_profile": f"{self.environment['CUSTOMER_IDENTIFIER']}.canvasmedical.com/patient/{patient_id}/edit",
                 "patient_id": patient_id,
                },
                status_code=HTTPStatus.ACCEPTED,
            )
        ]


    @api.post("/upsert")
    def upsert(self) -> list[Response | Effect]:
        """
            Given a patient and their metadata key/value pair,
            return a Patient Metadata upsert effect
        """
        body = self.request.json()

        # fetch all expected request body parameters
        # return error if any are not give to display to user
        try:
            patient_id = body["patient"]
            key = body["key"]
            value = body["value"]
        except KeyError:
            return [JSONResponse(
                {"message": "Missing one or more required fields: patient, key, value."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        patient_metadata = [{"key": key, "value": value}]
        return self.handle_metadata_upsert(patient_id, patient_metadata)

    @api.post("/bulk_upsert")
    def bulk_upsert(self) -> list[Response | Effect]:
        """
            Given a patient and list of their metadata key/value pair,
            return a Patient Metadata upsert effect
        """
        body = self.request.json()

        # fetch all expected request body parameters
        # return error if any are not give to display to user
        try:
            patient_id = body["patient"]
            patient_metadata = body['metadata']
        except KeyError:
            return [JSONResponse(
                {"message": "Missing one or more required fields: patient, metadata."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]


        return self.handle_metadata_upsert(patient_id, patient_metadata)
 