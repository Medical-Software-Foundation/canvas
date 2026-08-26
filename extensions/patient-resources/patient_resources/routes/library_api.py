"""Staff-authenticated endpoints for curating the resource library.

Two layers of access control meet here and they are deliberately separate.
``StaffSessionAuthMixin`` answers "is this a live staff session"; it cannot
answer "may this person edit a library that patients will read". That second
question is ``services/permissions.py``, re-asked on every write route -- the
read-only rendering in the front end is a convenience, not the enforcement.

Reads ``Staff`` and ``StaffRole`` and nothing else. Sharing lives in
``routes/share_api.py`` so that this class needs no patient access at all.
"""

from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from patient_resources.constants import STATUS_ACTIVE, STATUS_ARCHIVED
from patient_resources.routes.support import StaffRouteMixin
from patient_resources.services.catalog import (
    DuplicateResourceError,
    delete_resource,
    ResourceInUseError,
    create_resource,
    distinct_labels,
    get_resource,
    list_resources,
    normalize_limit,
    normalize_offset,
    set_status,
    update_resource,
)
from patient_resources.services.permissions import is_library_admin
from patient_resources.services.shares import (
    has_live_shares,
    resources_with_live_shares,
    resources_with_withdrawn_shares,
    revoke_resource_shares,
)
from patient_resources.services.serializers import serialize_resource
from patient_resources.services.validation import validate_resource


class LibraryAPI(StaffRouteMixin, StaffSessionAuthMixin, SimpleAPI):
    """Reading and curating the resource library."""

    PREFIX = "/library"

    def _curator(self) -> tuple[Any, list[Response | Effect] | None]:
        """The acting staff member if they may curate, else the refusal to return.

        Exactly one half is meaningful: when the refusal is ``None`` the staff
        member is present, and when it is not, the caller returns it untouched.
        """
        staff = self._acting_staff()
        if staff is None:
            return None, self._unauthenticated()
        if not is_library_admin(staff, self._config()):
            return None, self._forbidden()
        return staff, None

    def _resource_for_write(self) -> tuple[Any, list[Response | Effect] | None]:
        resource = get_resource(self._path_param("resource_id"))
        if resource is None:
            return None, self._not_found("That resource no longer exists.")
        return resource, None

    # --- reads -------------------------------------------------------------

    @api.get("/resources")
    def get_resources(self) -> list[Response | Effect]:
        """The library, searched and paged.

        ``can_edit`` travels in the response so the page can render itself
        read-only without a second round trip. ``include_archived`` is honored
        only for a curator, so a provider cannot reveal archived rows by adding a
        query parameter.
        """
        staff = self._acting_staff()
        if staff is None:
            return self._unauthenticated()

        can_edit = is_library_admin(staff, self._config())
        include_archived = can_edit and self._param("include_archived").lower() == "true"

        limit = normalize_limit(self._param("limit"))
        offset = normalize_offset(self._param("offset"))
        rows, total = list_resources(
            search=self._param("q"),
            label=self._param("label"),
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )

        # Only a curator sees the destructive controls, so only a curator's
        # response needs the flag that chooses between them. One set lookup for
        # the page rather than a check per row.
        live: set[Any] = set()
        withdrawn: set[Any] = set()
        if can_edit and rows:
            page = [row.dbid for row in rows]
            # Two lookups rather than deriving both from one, because a single
            # query returning every share row would drag back a row per patient.
            # Each of these returns at most one row per resource on the page.
            live = resources_with_live_shares(page)
            withdrawn = resources_with_withdrawn_shares(page)

        return [
            JSONResponse(
                {
                    "resources": [
                        serialize_resource(
                            row,
                            has_live_shares=(row.dbid in live) if can_edit else None,
                            has_withdrawn_shares=(
                                (row.dbid in withdrawn) if can_edit else None
                            ),
                        )
                        for row in rows
                    ],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "can_edit": can_edit,
                }
            )
        ]

    @api.get("/labels")
    def get_labels(self) -> list[Response | Effect]:
        """The labels in use, for the filter control."""
        if self._acting_staff() is None:
            return self._unauthenticated()
        return [JSONResponse({"labels": distinct_labels()})]

    # --- curation ----------------------------------------------------------

    @api.post("/resources")
    def post_resource(self) -> list[Response | Effect]:
        """Add a resource to the library."""
        staff, refusal = self._curator()
        if refusal is not None:
            return refusal

        body = self._json_object()
        if body is None:
            return self._invalid("The request body must be a JSON object.")

        errors = validate_resource(
            body.get("title"),
            body.get("url"),
            body.get("label"),
            body.get("default_note"),
        )
        if errors:
            return self._invalid("Check the highlighted fields.", errors)

        try:
            resource = create_resource(
                title=body["title"],
                url=body["url"],
                label=body.get("label", ""),
                default_note=body.get("default_note", ""),
                staff_dbid=staff.dbid,
            )
        except DuplicateResourceError as exc:
            return self._conflict(str(exc))

        return [JSONResponse(serialize_resource(resource), status_code=HTTPStatus.CREATED)]

    @api.put("/resources/<resource_id>")
    def put_resource(self) -> list[Response | Effect]:
        """Edit a resource.

        A changed link is refused once the resource has been shared, because the
        link is the identity of what a patient was given. See
        ``update_resource``.
        """
        staff, refusal = self._curator()
        if refusal is not None:
            return refusal

        resource, missing = self._resource_for_write()
        if missing is not None:
            return missing

        body = self._json_object()
        if body is None:
            return self._invalid("The request body must be a JSON object.")

        errors = validate_resource(
            body.get("title"),
            body.get("url"),
            body.get("label"),
            body.get("default_note"),
        )
        if errors:
            return self._invalid("Check the highlighted fields.", errors)

        try:
            updated = update_resource(
                resource,
                title=body["title"],
                url=body["url"],
                label=body.get("label", ""),
                default_note=body.get("default_note", ""),
                staff_dbid=staff.dbid,
            )
        except (ResourceInUseError, DuplicateResourceError) as exc:
            return self._conflict(str(exc))

        return [JSONResponse(serialize_resource(updated))]

    @api.post("/resources/<resource_id>/archive")
    def archive_resource(self) -> list[Response | Effect]:
        """Retire a resource.

        The only removal this plugin offers. A hard delete would orphan every
        share row and destroy the record of what patients were given. Existing
        shares keep their snapshot, but the resource stops being listed for
        everyone -- which is what makes a wrong link retractable.
        """
        return self._set_status(STATUS_ARCHIVED)

    @api.post("/resources/<resource_id>/restore")
    def restore_resource(self) -> list[Response | Effect]:
        """Put an archived resource back in the library."""
        return self._set_status(STATUS_ACTIVE)

    def _set_status(self, status: str) -> list[Response | Effect]:
        staff, refusal = self._curator()
        if refusal is not None:
            return refusal
        resource, missing = self._resource_for_write()
        if missing is not None:
            return missing
        return [
            JSONResponse(
                serialize_resource(set_status(resource, status, staff_dbid=staff.dbid))
            )
        ]

    @api.delete("/resources/<resource_id>")
    def delete_resource_route(self) -> list[Response | Effect]:
        """Remove a resource that never reached a patient.

        The narrow case this exists for is a resource added by mistake: a typo, a
        duplicate, or test data on a trial instance. Archiving hides such a row
        but leaves it in the library forever, and "we used to offer this" is the
        wrong thing to record about something that should never have existed.

        Anything a patient ever received is refused with a 409 and keeps Archive
        and Withdraw instead.
        """
        staff, refusal = self._curator()
        if refusal is not None:
            return refusal
        resource, missing = self._resource_for_write()
        if missing is not None:
            return missing

        try:
            delete_resource(resource)
        except ResourceInUseError as exc:
            return self._conflict(str(exc))

        return [JSONResponse({"deleted": True, "id": resource.dbid})]

    @api.post("/resources/<resource_id>/retract")
    def retract_resource(self) -> list[Response | Effect]:
        """Withdraw a resource from every patient who has it, and archive it.

        Deliberately heavier than archiving, because this changes what patients
        already hold: the front end asks for typed confirmation before calling
        it. Withdrawn resources stay visible to the patient as a dated notice
        rather than vanishing from a list they have already read.
        """
        staff, refusal = self._curator()
        if refusal is not None:
            return refusal
        resource, missing = self._resource_for_write()
        if missing is not None:
            return missing

        if not has_live_shares(resource):
            # Nothing to take back. Without this the call quietly revokes zero
            # rows and re-archives an archived resource, so a direct request
            # reports success for an action that did nothing.
            return self._conflict(
                "No patient currently holds this resource, so there is nothing to withdraw."
            )

        body = self._json_object() or {}
        withdrawn = revoke_resource_shares(
            resource_dbid=resource.dbid,
            reason=str(body.get("reason", "") or "").strip(),
        )
        set_status(resource, STATUS_ARCHIVED, staff_dbid=staff.dbid)
        return [JSONResponse({"withdrawn": withdrawn, "resource": serialize_resource(resource)})]
