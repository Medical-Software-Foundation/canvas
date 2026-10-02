"""The patient's own resource list.

Reachable by any signed-in patient, so ownership is the whole design of this
module. ``PatientSessionAuthMixin`` proves only that *some* patient has a live
session -- it does not bind the request to one, does not check the row exists,
and does not hand the id to this code.

The response to that is structural rather than a check: **no route here accepts
an identifier of any kind.** There is no patient parameter, no share id and no
resource id, so a patient cannot name another patient's row because nothing in
the surface takes a row. That is stronger than fetching by id and comparing the
owner afterwards, which is correct only as long as every fetch path remembers to
compare.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api

from patient_resources.constants import PORTAL_MAX_RESOURCES
from patient_resources.services.identity import patient_from_session
from patient_resources.services.serializers import (
    serialize_share_for_patient,
    serialize_withdrawn_share,
)
from patient_resources.services.shares import (
    live_shares_for_patient,
    mark_viewed,
    revoked_shares_for_patient,
)


class PortalAPI(PatientSessionAuthMixin, SimpleAPI):
    """Reads the signed-in patient's shared resources."""

    PREFIX = "/my-resources"

    @api.get("/")
    def get_my_resources(self) -> list[Response | Effect]:
        """Everything this patient's care team has shared with them."""
        patient = patient_from_session(self.request)
        if patient is None:
            # 401 rather than an empty list, and never a placeholder id. An empty
            # list would tell a patient their care team shared nothing, which is
            # a different and misleading statement.
            return [
                JSONResponse(
                    {"error": "Could not identify the signed-in patient."},
                    status_code=HTTPStatus.UNAUTHORIZED,
                )
            ]

        live = list(live_shares_for_patient(patient.dbid))
        withdrawn = list(revoked_shares_for_patient(patient.dbid))

        # Stamped after the list is built, and by patient rather than by row.
        # "Opened their list" is what we actually observed, and it avoids the
        # id-accepting endpoint that marking one row would require.
        mark_viewed(patient.dbid)

        return [
            JSONResponse(
                {
                    "resources": [serialize_share_for_patient(share) for share in live],
                    "withdrawn": [serialize_withdrawn_share(share) for share in withdrawn],
                    "truncated": len(live) >= PORTAL_MAX_RESOURCES,
                }
            )
        ]
