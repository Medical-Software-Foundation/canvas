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
from patient_resources.services.validation import note_length_error


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
            .only("id", "dbid", "first_name", "last_name", "birth_date", "mrn")
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
                    "patient": {
                        "name": _display_name(patient),
                        "birth_date": _display_birth_date(patient),
                        "mrn": _text(getattr(patient, "mrn", "")),
                    },
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

        notes, error = _notes(body.get("notes"), resource_ids)
        if error is not None:
            return self._invalid(error)

        try:
            result = share_resources(
                patient=patient,
                resource_dbids=resource_ids,
                staff_dbid=staff.dbid,
                notes=notes,
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


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _display_birth_date(patient: Any) -> str:
    """The patient's date of birth as MM/DD/YYYY, or empty.

    Formatted here rather than in the browser: ``toLocaleDateString`` follows the
    reader's locale, so an en-GB session renders 1979-04-12 as "12/04/1979",
    which reads as a different date than the same digits in a US clinical
    record. A date of birth is an identifier on this card, not a timestamp to
    localise -- unlike the portal's "shared on" dates, which are deliberately
    rendered in the patient's own locale.

    Returns empty rather than a placeholder when unset, so the caller drops the
    separator instead of showing "DOB None".
    """
    birth_date = getattr(patient, "birth_date", None)
    if birth_date is None:
        return ""
    strftime = getattr(birth_date, "strftime", None)
    if strftime is None:
        return _text(birth_date)
    return str(strftime("%m/%d/%Y"))


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


def _notes(raw: Any, resource_ids: list[int]) -> tuple[dict[int, str], str | None]:
    """Validate the per-patient notes. Returns ``(notes, error)``.

    Keyed by resource id, because JSON object keys are strings and the ids they
    name are integers -- a list parallel to ``resource_ids`` would silently
    mis-assign every note if the two ever fell out of step, and a note attached
    to the wrong resource is worse than no note at all.

    Anything naming a resource outside this send is rejected rather than
    dropped. It means the caller and this endpoint disagree about what is being
    sent, and guessing which of them is right is how a note lands on the wrong
    person's resource.
    """
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return {}, "Notes must be an object keyed by resource id."

    allowed = set(resource_ids)
    notes: dict[int, str] = {}
    for key, value in raw.items():
        try:
            resource_id = int(key)
        except (TypeError, ValueError):
            return {}, "Note keys must be resource ids."
        if resource_id not in allowed:
            return {}, "A note names a resource that is not being shared."
        if not isinstance(value, str):
            return {}, "A note must be text."
        length_error = note_length_error(value)
        if length_error is not None:
            return {}, length_error
        notes[resource_id] = value
    return notes, None
