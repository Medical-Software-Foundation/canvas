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
    NumberFormat,
    adopt_number,
    adoptable_patients,
    adopted_count,
    assign_number,
    backfill_complete,
    mark_backfill_complete,
    next_number,
    number_effects,
    source_numbers,
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

    def _format(self) -> NumberFormat:
        return NumberFormat.from_secrets(self.secrets)

    def _status(self) -> dict[str, int | bool | str]:
        fmt = self._format()
        return {
            "patients": PatientProxy.objects.count(),
            "numbered": PatientNumber.objects.count(),
            "remaining": unnumbered_patients().count(),
            "backfill_complete": backfill_complete(),
            "source_system": fmt.source_system,
            "adopted": adopted_count(fmt),
            "next_patient_id": fmt.format(next_number()),
        }

    @api.get("/admin")
    def admin_page(self) -> list[Response | Effect]:
        """Render the admin page, or a not-authorized notice."""
        authorized = self._is_admin()
        context: dict[str, int | bool | str] = {"authorized": authorized}
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
        """Number the next batch of unnumbered patients.

        Patients whose source ID (SOURCE_IDENTIFIER_SYSTEM) fits the format keep that number. Only
        once none are left to adopt is anyone else numbered, starting after the highest number in
        use, so a sequential number can never take a number that belongs to a source ID.
        """
        if not self._is_admin():
            return [JSONResponse({"error": "Not authorized"}, status_code=HTTPStatus.FORBIDDEN)]

        fmt = self._format()
        effects: list[Effect] = []
        adopted: list[int] = []
        assigned: list[int] = []

        candidates, adoptable_total = adoptable_patients(fmt, limit=BATCH_SIZE)
        for patient, number, source_value in candidates:
            if adopt_number(patient, number):
                effects.extend(number_effects(patient.id, number, fmt, searchable_as=source_value))
                adopted.append(number)

        conflicts = 0
        room = BATCH_SIZE - len(adopted)
        # Every adoptable patient fit in this batch, so nothing is left to adopt. (One that lost a
        # race for its number now has a taken source number and is numbered below.)
        if room > 0 and adoptable_total <= BATCH_SIZE:
            # Anyone still holding a source ID here has one whose number is already taken.
            unadopted = source_numbers(fmt)
            for patient in unnumbered_patients()[:room]:
                number, newly_assigned = assign_number(patient)
                if newly_assigned:
                    effects.extend(number_effects(patient.id, number, fmt))
                    assigned.append(number)
                    if patient.dbid in unadopted:
                        conflicts += 1
                        log.warning(
                            f"patient_numbering: patient {patient.id} source ID number "
                            f"{unadopted[patient.dbid][0]} was already taken, assigned {number}"
                        )

        remaining = unnumbered_patients().count()
        if remaining == 0:
            mark_backfill_complete()

        numbers = adopted + assigned
        log.info(
            f"patient_numbering: backfill adopted {len(adopted)}, assigned {len(assigned)}, "
            f"{conflicts} conflicts, {remaining} remaining"
        )
        return [
            JSONResponse(
                {
                    "assigned": len(numbers),
                    "adopted": len(adopted),
                    "conflicts": conflicts,
                    "first": fmt.format(numbers[0]) if numbers else None,
                    "last": fmt.format(numbers[-1]) if numbers else None,
                    "remaining": remaining,
                    "backfill_complete": remaining == 0,
                }
            ),
            *effects,
        ]
