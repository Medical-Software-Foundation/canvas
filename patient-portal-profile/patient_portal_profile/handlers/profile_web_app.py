from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus
from canvas_sdk.v1.data.patient import Patient

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ProfileWebApp(PatientSessionAuthMixin, SimpleAPI):
    """Serves the patient profile page for the patient portal."""

    PREFIX = "/app"

    @api.get("/profile")
    def get_profile(self) -> list[Response | Effect]:
        """Render and serve the patient profile page."""
        patient_id = self.request.headers["canvas-logged-in-user-id"]

        patient = (
            Patient.objects.select_related("user")
            .prefetch_related("addresses")
            .get(id=patient_id)
        )

        portal_user = (
            patient.user if patient.user and patient.user.is_portal_registered else None
        )

        care_team_qs = CareTeamMembership.objects.values(
            "staff__first_name",
            "staff__last_name",
            "staff__prefix",
            "staff__suffix",
            "staff__photos__url",
            "role_display",
        ).filter(
            patient__id=patient_id,
            status=CareTeamMembershipStatus.ACTIVE,
        )

        care_team = []
        for member in care_team_qs:
            first = member["staff__first_name"] or ""
            last = member["staff__last_name"] or ""
            prefix = member["staff__prefix"] or ""
            suffix = member["staff__suffix"] or ""

            name_parts = [p for p in (prefix, first, last) if p]
            display_name = " ".join(name_parts)
            if suffix:
                display_name = f"{display_name}, {suffix}"

            care_team.append(
                {
                    "display_name": display_name,
                    "photo_url": member["staff__photos__url"] or "",
                    "role": member["role_display"] or "",
                }
            )

        addresses = list(patient.addresses.all())

        preferred_pharmacy = patient.preferred_pharmacy

        context = {
            "patient": patient,
            "photo_url": patient.photo_url,
            "preferred_full_name": patient.preferred_full_name,
            "portal_user": portal_user,
            "addresses": addresses,
            "care_team": care_team,
            "preferred_pharmacy": preferred_pharmacy,
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
