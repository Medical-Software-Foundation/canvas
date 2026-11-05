from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.immunization import Immunization, ImmunizationStatement
from canvas_sdk.v1.data.patient import Patient

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

# Source labels surfaced to the patient on each row.
_SOURCE_ADMINISTERED = "Administered here"
_SOURCE_REPORTED = "Reported history"

# Fallback shown when a record carries no coding display/code at all.
_UNNAMED_VACCINE = "Immunization"


def _best_display(codings: list[Any]) -> str:
    """Pick a human-readable vaccine name, preferring a CVX coding."""
    cvx = next((c for c in codings if "cvx" in (c.system or "").lower()), None)
    chosen = cvx or (codings[0] if codings else None)
    if chosen is None:
        return _UNNAMED_VACCINE
    return chosen.display or chosen.code or _UNNAMED_VACCINE


def _build_rows(patient_id: str) -> list[dict[str, Any]]:
    """Merge administered immunizations and reported statements, newest first.

    The model manager already excludes soft-deleted rows; we pass ``deleted=False``
    explicitly to mirror Canvas's own immunization queries. We intentionally do NOT
    filter on ``status``: a committed "Immunize" command leaves ``status`` at its
    default ``in-progress`` (it is never set to ``completed``), so a status filter
    would hide every administered vaccine. ``committer``/``entered_in_error`` are not
    exposed on the SDK model, so commit/retraction state cannot be filtered here.
    Two bulk queries with prefetched codings — no per-row query (no N+1). Rows
    without a date sort last.
    """
    rows: list[dict[str, Any]] = []

    immunizations = (
        Immunization.objects.for_patient(patient_id)
        .filter(deleted=False)
        .prefetch_related("codings")
    )
    for imm in immunizations:
        rows.append(
            {
                "name": _best_display(list(imm.codings.all())),
                "date": imm.date_ordered,
                "date_display": imm.date_ordered.isoformat()
                if imm.date_ordered
                else "",
                "source": _SOURCE_ADMINISTERED,
                "manufacturer": imm.manufacturer or "",
                "lot_number": imm.lot_number or "",
                "route": imm.route or "",
                "comment": "",
            }
        )

    statements = (
        ImmunizationStatement.objects.for_patient(patient_id)
        .filter(deleted=False)
        .prefetch_related("coding")
    )
    for stmt in statements:
        rows.append(
            {
                "name": _best_display(list(stmt.coding.all())),
                "date": stmt.date,
                "date_display": stmt.date.isoformat() if stmt.date else "",
                "source": _SOURCE_REPORTED,
                "manufacturer": "",
                "lot_number": "",
                "route": "",
                "comment": stmt.comment or "",
            }
        )

    # Newest first; undated rows fall to the bottom.
    rows.sort(key=lambda r: r["date"] or date.min, reverse=True)
    return rows


class VaccineCardWebApp(PatientSessionAuthMixin, SimpleAPI):
    """Serves the patient's immunization record page for the patient portal."""

    PREFIX = "/app"

    @api.get("/card")
    def get_card(self) -> list[Response | Effect]:
        """Render and serve the patient's vaccine card page."""
        patient_id = self.request.headers["canvas-logged-in-user-id"]

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [
                Response(
                    b"Patient not found",
                    status_code=HTTPStatus.NOT_FOUND,
                    content_type="text/plain",
                )
            ]

        rows = _build_rows(patient_id)

        context = {
            "patient_name": patient.preferred_full_name,
            "rows": rows,
            "cache_bust": _CACHE_BUST,
        }

        return [
            HTMLResponse(
                render_to_string("static/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/main.js")
    def get_main_js(self) -> list[Response | Effect]:
        """Serve the main JavaScript file."""
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def get_styles_css(self) -> list[Response | Effect]:
        """Serve the CSS styles file."""
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
