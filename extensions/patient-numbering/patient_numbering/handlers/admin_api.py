"""Admin API behind the Patient Numbering app.

Access requires a logged-in staff session and the staff id to be listed in ADMIN_STAFF_IDS.
An unset or empty ADMIN_STAFF_IDS denies everyone.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from logger import log
from patient_numbering.models import PatientNumber, PatientProxy
from patient_numbering.numbering import (
    assign_number,
    backfill_complete,
    mark_backfill_complete,
    number_effects,
    unnumbered_patients,
)

BATCH_SIZE = 100


class PatientNumberingAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """Status and backfill endpoints for the Patient Numbering admin app."""

    def _is_admin(self) -> bool:
        """True only when the logged-in staff member is listed in ADMIN_STAFF_IDS."""
        raw = (self.secrets.get("ADMIN_STAFF_IDS") or "").strip()
        if not raw:
            log.warning("patient_numbering: ADMIN_STAFF_IDS not configured, denying access")
            return False
        admin_ids = {item.strip() for item in raw.split(",") if item.strip()}
        return self.request.headers.get("canvas-logged-in-user-id", "") in admin_ids

    def _status(self) -> dict[str, int | bool]:
        return {
            "patients": PatientProxy.objects.count(),
            "numbered": PatientNumber.objects.count(),
            "remaining": unnumbered_patients().count(),
            "backfill_complete": backfill_complete(),
        }

    @api.get("/admin")
    def admin_page(self) -> list[Response | Effect]:
        """Render the admin page, or a not-authorized notice."""
        authorized = self._is_admin()
        context: dict[str, int | bool] = {"authorized": authorized}
        if authorized:
            context.update(self._status())
        return [HTMLResponse(render_to_string("templates/admin.html", context) or "")]

    @api.get("/status")
    def status(self) -> list[Response | Effect]:
        """Report how many patients are numbered and whether the backfill is done."""
        if not self._is_admin():
            return [JSONResponse({"error": "Not authorized"}, status_code=HTTPStatus.FORBIDDEN)]
        return [JSONResponse(self._status())]

    @api.post("/backfill")
    def backfill(self) -> list[Response | Effect]:
        """Number the next batch of unnumbered patients, oldest first."""
        if not self._is_admin():
            return [JSONResponse({"error": "Not authorized"}, status_code=HTTPStatus.FORBIDDEN)]

        effects: list[Effect] = []
        assigned: list[int] = []
        for patient in unnumbered_patients()[:BATCH_SIZE]:
            number, newly_assigned = assign_number(patient)
            if newly_assigned:
                effects.extend(number_effects(patient.id, number))
                assigned.append(number)

        remaining = unnumbered_patients().count()
        if remaining == 0:
            mark_backfill_complete()

        log.info(f"patient_numbering: backfill assigned {len(assigned)}, {remaining} remaining")
        return [
            JSONResponse(
                {
                    "assigned": len(assigned),
                    "first": assigned[0] if assigned else None,
                    "last": assigned[-1] if assigned else None,
                    "remaining": remaining,
                    "backfill_complete": remaining == 0,
                }
            ),
            *effects,
        ]
