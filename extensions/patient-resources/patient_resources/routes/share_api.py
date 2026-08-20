"""Staff-authenticated endpoints for giving a patient resources.

Split from the library API for two reasons. The manifest can then declare that
this class -- and only this class -- reads ``Patient``, and curation stays free of
patient access entirely. Sharing is also open to any authenticated staff member,
whereas curation is not, so keeping them apart keeps that difference visible
rather than buried in per-route checks.
"""

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data import Patient
from django.db import IntegrityError

from patient_resources.constants import MAX_SHARE_BATCH
from patient_resources.routes.support import StaffRouteMixin
from patient_resources.services.shares import live_shares_for_patient, share_resources
from patient_resources.services.identity import id_candidates
from patient_resources.services.serializers import serialize_share_for_staff


class ShareAPI(StaffRouteMixin, StaffSessionAuthMixin, SimpleAPI):
    """Patient lookup for the picker, and the send itself."""

    PREFIX = "/shares"

    @staticmethod
    def _resolve_patient(raw: str) -> Any | None:
        """Resolve a patient key, trying every form the 32-character column may hold.

        ``Patient.id`` is ``CharField(max_length=32)``, not a UUID field, so a
        dashed key from the chart context misses an undashed stored value and the
        lookup comes back empty rather than raising. One shipped plugin in this
        repo documents the opposite and is wrong about it.
        """
        candidates = id_candidates(raw)
        if not candidates:
            return None
        return (
            Patient.objects.filter(id__in=list(candidates))
            .only("id", "dbid", "first_name", "last_name")
            .first()
        )

    @api.get("/patients/<patient_id>")
    def get_patient(self) -> list[Response | Effect]:
        """Confirm the chart's patient exists, and say what they already have.

        The picker uses this for its header and to mark rows it should not offer
        twice. Any authenticated staff member may call it: they are already
        looking at this patient's chart.
        """
        if self._acting_staff() is None:
            return self._unauthenticated()

        patient = self._resolve_patient(self._path_param("patient_id"))
        if patient is None:
            return self._not_found("That patient could not be found.")

        existing = list(live_shares_for_patient(patient.dbid))
        return [
            JSONResponse(
                {
                    "patient": {"name": _display_name(patient)},
                    "shared": [serialize_share_for_staff(share) for share in existing],
                }
            )
        ]

    @api.post("/")
    def post_shares(self) -> list[Response | Effect]:
        """Give a patient one or more resources.

        Open to any authenticated staff member: the locked scope is that
        providers may share but not edit.
        """
        staff = self._acting_staff()
        if staff is None:
            return self._unauthenticated()

        body = self._json_object()
        if body is None:
            return self._invalid("The request body must be a JSON object.")

        patient = self._resolve_patient(str(body.get("patient", "") or ""))
        if patient is None:
            return self._not_found("That patient could not be found.")

        resource_ids, error = _resource_ids(body.get("resource_ids"))
        if error is not None:
            return self._invalid(error)

        try:
            result = share_resources(
                patient=patient, resource_dbids=resource_ids, staff_dbid=staff.dbid
            )
        except IntegrityError:
            # The already-shared pre-check races with a second provider sending
            # the same resource. The unique constraint is the real guard; this
            # reports the race as "already shared" rather than a 500.
            return [
                JSONResponse(
                    {
                        "created": 0,
                        "already_shared": len(resource_ids),
                        "skipped_unavailable": 0,
                        "shared_resource_ids": [],
                        "shares": [],
                    }
                )
            ]

        # 200 rather than 201: the call is partially idempotent, and the counts
        # matter more than the creation. A provider needs to be told that two
        # went out, one was already there and one has since been archived.
        return [
            JSONResponse(
                {
                    "created": len(result.created),
                    "already_shared": result.already_shared,
                    "skipped_unavailable": result.skipped_unavailable,
                    "shared_resource_ids": [row.resource_id for row in result.created],
                    "shares": [serialize_share_for_staff(row) for row in result.created],
                }
            )
        ]


def _display_name(patient: Any) -> str:
    parts = (
        getattr(patient, "first_name", "") or "",
        getattr(patient, "last_name", "") or "",
    )
    return " ".join(part for part in parts if part)


def _resource_ids(raw: Any) -> tuple[list[int], str | None]:
    """Validate the requested resource ids. Returns ``(ids, error)``."""
    if not isinstance(raw, list) or not raw:
        return [], "Select at least one resource to share."
    if len(raw) > MAX_SHARE_BATCH:
        return [], f"Share at most {MAX_SHARE_BATCH} resources at a time."

    ids: list[int] = []
    for value in raw:
        # Booleans are ints in Python, so `True` would otherwise pass as
        # resource 1 and share something nobody selected.
        if isinstance(value, bool) or not isinstance(value, int):
            return [], "Resource ids must be whole numbers."
        ids.append(value)
    return ids, None
