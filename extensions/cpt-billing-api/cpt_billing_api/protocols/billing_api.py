"""SimpleAPI endpoint for adding CPT billing line items to Canvas notes."""

from datetime import date
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.billing_line_item import AddBillingLineItem
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPIRoute
from canvas_sdk.v1.data.assessment import Assessment
from canvas_sdk.v1.data.charge_description_master import ChargeDescriptionMaster
from canvas_sdk.v1.data.note import Note
from logger import log


class ValidationError(Exception):
    """Exception raised for validation errors."""

    pass


class NotFoundError(Exception):
    """Exception raised when a resource is not found."""

    pass


class BillingAPI(APIKeyAuthMixin, SimpleAPIRoute):
    """API endpoint for adding CPT billing codes to Canvas notes.

    Endpoint: POST /billing/add-line-item
    Authentication: API Key (Bearer token)

    Request body:
    {
        "note_id": "uuid-of-note",
        "cpt_code": "99213",
        "units": 1,  # optional, defaults to 1
        "icd10_codes": ["E11.9", "I10"]  # optional - ICD-10 codes to link as diagnosis pointers
    }
    """

    PATH = "/billing/add-line-item"

    def post(self) -> list[Response | Effect]:
        """Handle POST request to add a billing line item to a note.

        Returns:
            List containing a JSONResponse with success/error information
            and optionally an AddBillingLineItem effect.
        """
        try:
            # Parse and validate request body
            body = self._parse_request_body()
            note_id = self._validate_required_field(body, "note_id")
            cpt_code = self._validate_required_field(body, "cpt_code")
            units = body.get("units", 1)
            icd10_codes = body.get("icd10_codes", [])

            # Validate note exists
            note_dbid = self._validate_note_exists(note_id)

            # Validate CPT code
            self._validate_cpt_code(cpt_code)

            # Find assessments with matching ICD-10 codes if provided
            assessment_ids, found_icd10_codes, not_found_icd10_codes = self._find_assessments_by_icd10(icd10_codes, note_dbid)

            # Create the billing line item effect
            effect = AddBillingLineItem(
                note_id=note_id,
                cpt=cpt_code,
                units=units,
                assessment_ids=assessment_ids,
            )
            log.info(
                f"Adding billing line item: note_id={note_id}, "
                f"cpt={cpt_code}, units={units}, assessment_ids={assessment_ids}, "
                f"found_icd10_codes={found_icd10_codes}, not_found_icd10_codes={not_found_icd10_codes}"
            )

            return [
                effect.apply(),
                JSONResponse(
                    {
                        "status": "success",
                        "message": "Billing line item sent to Canvas successfully",
                        "note_id": str(note_id),
                        "cpt_code": cpt_code,
                        "units": units,
                        "found_icd10_codes": found_icd10_codes,
                        "not_found_icd10_codes": not_found_icd10_codes,
                        "assessment_ids": assessment_ids,
                    },
                    status_code=HTTPStatus.CREATED,
                ),
            ]

        except ValidationError as e:
            log.warning(f"Validation error: {str(e)}")
            return [
                JSONResponse(
                    {"status": "error", "error": "Invalid request", "details": str(e)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        except NotFoundError as e:
            log.warning(f"Object not found: {str(e)}")
            return [
                JSONResponse(
                    {"status": "error", "error": "Resource not found", "details": str(e)},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        except CPTCodeValidationError as e:
            log.warning(f"CPT code validation error: {str(e)}")
            return [
                JSONResponse(
                    {"status": "error", "error": "Invalid CPT code", "details": str(e)},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]
        except Exception as e:
            log.error(f"Unexpected error in billing API: {str(e)}", exc_info=True)
            return [
                JSONResponse(
                    {
                        "status": "error",
                        "error": "Internal server error",
                        "details": "An unexpected error occurred while processing the request",
                    },
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    def _parse_request_body(self) -> dict[str, Any]:
        """Parse the JSON request body.

        Returns:
            Dictionary containing the parsed request body.

        Raises:
            ValidationError: If the request body is not valid JSON.
        """
        try:
            body = self.request.json()
            if not isinstance(body, dict):
                raise ValidationError("Request body must be a JSON object")
            return body
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid JSON in request body: {str(e)}") from e

    def _validate_required_field(self, body: dict[str, Any], field_name: str) -> str:
        """Validate that a required field is present in the request body.

        Args:
            body: The parsed request body dictionary.
            field_name: The name of the required field.

        Returns:
            The value of the field as a string.

        Raises:
            ValidationError: If the field is missing or empty.
        """
        value = body.get(field_name)
        if not value:
            raise ValidationError(f"Missing required field: {field_name}")
        return str(value).strip()

    def _validate_note_exists(self, note_id: str) -> Note:
        """Validate that a note with the given ID exists.

        Args:
            note_id: The UUID of the note to validate.

        Returns:
            The Note object if it exists.

        Raises:
            NotFoundError: If the note does not exist.
        """
        note_dbid = Note.objects.filter(id=note_id).values_list('dbid', flat=True).first()
        if not note_dbid:
            raise NotFoundError(
                f"Note with ID {note_id} does not exist"
            )
        return note_dbid

    def _validate_cpt_code(self, cpt_code: str) -> None:
        """Validate that a CPT code is valid, not expired, and effective.

        This validation checks the ChargeDescriptionMaster to ensure:
        1. The CPT code exists in the system
        2. The code is not expired (expiration_date is None or in the future)
        3. The code is effective (effective_date is None or in the past/today)

        Args:
            cpt_code: The CPT code to validate.

        Raises:
            CPTCodeValidationError: If the CPT code is not valid, expired, or not yet effective.
        """
        today = date.today()

        try:
            # Query ChargeDescriptionMaster for the CPT code
            cdm_entry = ChargeDescriptionMaster.objects.get(cpt_code=cpt_code)
        except Exception as e:
            # Catch any exception from the query (including DoesNotExist)
            raise CPTCodeValidationError(
                f"CPT code '{cpt_code}' not found in ChargeDescriptionMaster"
            ) from e

        # Check if the code is expired
        if cdm_entry.expiration_date and cdm_entry.expiration_date < today:
            raise CPTCodeValidationError(
                f"CPT code '{cpt_code}' is expired. "
                f"Expiration date: {cdm_entry.expiration_date}"
            )

        # Check if the code is effective yet
        if cdm_entry.effective_date and cdm_entry.effective_date > today:
            raise CPTCodeValidationError(
                f"CPT code '{cpt_code}' is not yet effective. "
                f"Effective date: {cdm_entry.effective_date}"
            )

        log.info(
            f"CPT code '{cpt_code}' validated successfully. "
            f"Effective: {cdm_entry.effective_date}, "
            f"Expires: {cdm_entry.expiration_date or 'Never'}"
        )

    def _find_assessments_by_icd10(
        self, icd10_codes: list[str], note_dbid: int
    ) -> tuple[list[str], list[str], list[str]]:
        """Find assessments in a note that match the given ICD-10 codes.

        Args:
            icd10_codes: List of ICD-10 codes to search for.
            note_dbid: The database ID of the note.

        Returns:
            List of assessment UUIDs that have conditions with matching ICD-10 codes.
            List of ICD-10 codes that were found.
            List of ICD-10 codes that were not found.
        """
        if not icd10_codes:
            return [], [], []

        filtered_icd10_codes = [icd10_code.upper().replace(".", "") for icd10_code in icd10_codes]
        found_icd10_codes = []
        matching_assessment_ids = []

        # Get all assessments for this note
        assessments = Assessment.objects.filter(note_id=note_dbid)

        for assessment in assessments:
            if not assessment.condition:
                continue

            # Check if any of the condition's codings match the requested ICD-10 codes
            for coding in assessment.condition.codings.all():
                # Check both ICD-10 system identifiers
                if coding.system == "ICD-10":
                    if coding.code.upper().replace(".", "") in filtered_icd10_codes:
                        matching_assessment_ids.append(str(assessment.id))
                        log.info(
                            f"Found assessment {assessment.id} with ICD-10 code {coding.code}"
                        )
                        found_icd10_codes.append(coding.code)
                        break  # Found a match for this assessment, move to next

        if not matching_assessment_ids:
            log.warning(
                f"No assessments found for ICD-10 codes {icd10_codes} in note {note_dbid}"
            )

        not_found_icd10_codes = [icd10_code for icd10_code in filtered_icd10_codes if icd10_code not in found_icd10_codes]
        if not_found_icd10_codes:
            log.warning(
                f"ICD-10 codes {not_found_icd10_codes} not found in note {note_dbid}"
            )

        return matching_assessment_ids, found_icd10_codes, not_found_icd10_codes


class CPTCodeValidationError(Exception):
    """Exception raised when CPT code validation fails."""

    pass
