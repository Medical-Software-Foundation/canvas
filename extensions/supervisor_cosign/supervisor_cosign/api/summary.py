"""The co-sign summary page, its assets, and its scoped JSON feed.

Gating is asymmetric on purpose: a ``provider_menu_item``
application has no ``visible()`` hook, so the menu label cannot be hidden and
any clinician may click it. The page therefore answers **200 with a neutral
placeholder** for someone who is neither a supervisor nor on the oversight
list — they have done nothing wrong, and the placeholder must not advertise
that an allowlist exists. The data route, which carries patient names, answers
**403**. The page is courtesy; the JSON route is the boundary.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from supervisor_cosign.helpers.attestation_templates import (
    DEFAULT_TEMPLATE_KEY,
    attestation_options,
)
from supervisor_cosign.helpers.cosign_access import OVERSIGHT_SECRET, viewer_role
from supervisor_cosign.helpers.staff_allowlist import requesting_staff_id, staff_allowed
from supervisor_cosign.helpers.summary_queries import (
    notes_rows,
    records_rows,
    window_bounds,
)
from supervisor_cosign.helpers.supervision import supervised_staff, supervises_someone


#: Stands in for the supervisee name in the page's attestation options. Not
#: the plugin's ``{{supervisee}}`` placeholder, which Django would strip.
SUPERVISEE_TOKEN = "__SUPERVISEE__"


def _sorted_options(mapping: dict) -> list[dict]:
    options = [{"id": key, "name": mapping[key]} for key in mapping]
    options.sort(key=_option_name)
    return options


def _option_name(option: dict) -> str:
    return option["name"]


class SupervisorCoSignSummaryAPI(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = "/summary"

    def _role(self) -> dict:
        # Read the header inside the route method. Canvas instantiates a
        # separate handler for SIMPLE_API_AUTHENTICATE than for
        # SIMPLE_API_REQUEST, so anything stashed on self during authenticate
        # is gone by now - api/handlers.py carries the same note.
        staff_id = requesting_staff_id(self.request)
        # Skip the database probe entirely when the allowlist already answers:
        # oversight access does not depend on supervising anyone.
        if staff_id and staff_allowed(self.secrets, OVERSIGHT_SECRET, staff_id):
            return viewer_role(self.secrets, staff_id, False)
        return viewer_role(self.secrets, staff_id, supervises_someone(staff_id))

    @api.get("/view")
    def view(self) -> list[Response | Effect]:
        role = self._role()
        if not role["allowed"]:
            # The placeholder carries no explanation, not even in an HTML
            # comment: comments ship to the browser, and naming the gate would
            # advertise the surface the gate exists to keep quiet. The reason
            # lives in this module's docstring instead.
            return [
                HTMLResponse(
                    render_to_string("templates/cosign_summary_unavailable.html", {}),
                    status_code=HTTPStatus.OK,
                )
            ]
        start, end = window_bounds("", "")
        context = {
            "oversight": role["oversight"],
            "start": start,
            "end": end,
            # The attestation prose is substituted server-side with a
            # neutral token, and the JS swaps the token for the row's own
            # supervisee. The plugin's native placeholder cannot travel to the
            # client: this page is Django-rendered and a literal {{ }} is
            # stripped out of the output before the browser ever sees it.
            "attestation_options": attestation_options(SUPERVISEE_TOKEN),
            "default_template": DEFAULT_TEMPLATE_KEY,
        }
        return [
            HTMLResponse(
                render_to_string("templates/cosign_summary.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/styles.css")
    def styles(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("templates/cosign_summary.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/app.js")
    def app_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("templates/cosign_summary.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/filters")
    def filters(self) -> list[Response | Effect]:
        role = self._role()
        if not role["allowed"]:
            return [self._denied()]
        if role["oversight"]:
            team = supervised_staff(None)
        else:
            team = supervised_staff([role["staff_id"]])
        supervisors = {}
        for member in team:
            if member["supervisor_id"]:
                supervisors[member["supervisor_id"]] = member["supervisor_name"]
        return [
            JSONResponse(
                {
                    "oversight": role["oversight"],
                    "supervisees": [
                        {"id": m["id"], "name": m["name"]} for m in team
                    ],
                    # A plain supervisor gets no supervisor list: there is
                    # exactly one possible value and it is themselves.
                    "supervisors": _sorted_options(supervisors) if role["oversight"] else [],
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/data")
    def data(self) -> list[Response | Effect]:
        role = self._role()
        if not role["allowed"]:
            return [self._denied()]
        params = self.request.query_params
        mode = str(params.get("mode") or "records").strip()
        if mode == "notes":
            result = notes_rows(role, params, self.secrets)
        else:
            mode = "records"
            result = records_rows(role, params, self.secrets)
        result["mode"] = mode
        # The summary already covers the whole filtered set, computed before
        # the page was sliced. Do not recompute it from result["rows"].
        result["viewer"] = {
            "staff_id": role["staff_id"],
            "oversight": role["oversight"],
            "supervisor": role["supervisor"],
        }
        return [JSONResponse(result, status_code=HTTPStatus.OK)]

    def _denied(self) -> Response:
        # Says nothing about supervisors or allowlists, for the same reason
        # the placeholder page does not.
        return JSONResponse(
            {"status": "error", "message": "Not available."},
            status_code=HTTPStatus.FORBIDDEN,
        )
