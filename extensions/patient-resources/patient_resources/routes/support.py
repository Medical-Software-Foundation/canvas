"""Request-boundary helpers shared by the staff-facing API classes.

Kept in one place because both staff classes need identical handling of the same
three untrusted things -- query parameters, path parameters and the request body
-- and two copies of that is two places for a boundary check to drift.
"""

from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response

from patient_resources.services.config import PatientResourcesConfig
from patient_resources.services.identity import staff_from_session


class StaffRouteMixin:
    """Parameter reading, staff identity, and the standard refusals.

    ``request`` and ``secrets`` are declared here only so this mixin type-checks
    on its own. They are supplied at runtime by ``SimpleAPI``, which every class
    using this mixin also inherits from.
    """

    request: Any
    secrets: dict[str, Any]

    def _config(self) -> PatientResourcesConfig:
        return PatientResourcesConfig.from_secrets(getattr(self, "secrets", None))

    def _param(self, name: str) -> str:
        params = getattr(self.request, "query_params", None) or {}
        return str(params.get(name, "") or "").strip()

    def _path_param(self, name: str) -> str:
        params = getattr(self.request, "path_params", None) or {}
        return str(params.get(name, "") or "").strip()

    def _json_object(self) -> dict[str, Any] | None:
        """The request body, if it is a JSON object.

        ``request.json()`` hands back whatever the caller sent, so a bare list or
        ``null`` would make every ``.get()`` downstream raise. Checked once here
        rather than defended against in each reader.
        """
        try:
            body = self.request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _acting_staff(self) -> Any | None:
        """The signed-in staff member, from the session header only.

        Never from the request body: a caller could name anyone, and a resource
        attributed to the wrong person is a false audit trail.
        """
        return staff_from_session(self.request)

    @staticmethod
    def _unauthenticated() -> list[Response | Effect]:
        return [
            JSONResponse(
                {"error": "Could not identify the signed-in staff member."},
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        ]

    @staticmethod
    def _forbidden() -> list[Response | Effect]:
        return [
            JSONResponse(
                {"error": "Only administrators can change the resource library."},
                status_code=HTTPStatus.FORBIDDEN,
            )
        ]

    @staticmethod
    def _invalid(
        message: str, field_errors: dict[str, str] | None = None
    ) -> list[Response | Effect]:
        payload: dict[str, Any] = {"error": message}
        if field_errors:
            payload["field_errors"] = field_errors
        return [JSONResponse(payload, status_code=HTTPStatus.BAD_REQUEST)]

    @staticmethod
    def _not_found(message: str) -> list[Response | Effect]:
        return [JSONResponse({"error": message}, status_code=HTTPStatus.NOT_FOUND)]

    @staticmethod
    def _conflict(message: str) -> list[Response | Effect]:
        return [JSONResponse({"error": message}, status_code=HTTPStatus.CONFLICT)]
