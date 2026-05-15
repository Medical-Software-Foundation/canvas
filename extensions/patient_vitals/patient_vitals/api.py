"""VitalsAPI - patient-portal SimpleAPI protocol for patient_vitals.

Two routes:

* ``GET  /plugin-io/api/patient_vitals/page``         → HTML page (tile grid).
* ``POST /plugin-io/api/patient_vitals/observations`` → JSON, action dispatched
  to :func:`vitals_data.aggregate_summary` or :func:`vitals_data.history_for_code`.

Auth is enforced by :class:`PatientSessionAuthMixin`. The patient id used for
all queries is read from the ``canvas-logged-in-user-id`` header (set by the
auth mixin) — *never* from the request body, so a patient cannot read another
patient's vitals by spoofing a JSON field.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from logger import log

from patient_vitals.vitals_data import (
    UnknownVitalCode,
    aggregate_summary,
    history_for_code,
)


class VitalsAPI(PatientSessionAuthMixin, SimpleAPI):
    """Patient-portal HTTP API for vitals."""

    PREFIX = ""

    @api.get("/page")
    def page(self) -> list[Response | Effect]:
        """Serve the vitals HTML page (CSS + JS embedded)."""
        patient_id = self.request.headers.get("canvas-logged-in-user-id")
        log.info("VitalsAPI.page patient=%s", patient_id)
        return [
            HTMLResponse(
                render_to_string("templates/vitals_page.html", {}),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/observations")
    def observations(self) -> list[Response | Effect]:
        """Dispatch JSON actions: ``list_summary`` or ``history``."""
        patient_id = self.request.headers.get("canvas-logged-in-user-id")
        body = self.request.json() or {}
        action = body.get("action")
        log.info("VitalsAPI.observations patient=%s action=%s", patient_id, action)

        try:
            if action == "list_summary":
                vitals = aggregate_summary(patient_id)
                return [
                    JSONResponse(
                        {"status": "success", "data": {"vitals": vitals}},
                        status_code=HTTPStatus.OK,
                    )
                ]
            if action == "history":
                code = body.get("code")
                payload = history_for_code(patient_id, code)
                return [
                    JSONResponse(
                        {"status": "success", "data": payload},
                        status_code=HTTPStatus.OK,
                    )
                ]
            return [
                JSONResponse(
                    {"status": "error", "message": f"unknown action: {action!r}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        except UnknownVitalCode:
            return [
                JSONResponse(
                    {"status": "error", "message": "unknown vital code"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        except Exception as exc:
            log.error("VitalsAPI.observations internal error: %s", exc, exc_info=True)
            return [
                JSONResponse(
                    {"status": "error", "message": "internal error"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]
