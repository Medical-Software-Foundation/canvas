"""SimpleAPI for the patient portal.

Serves the two portal pages (My Records, My Profile) and the patient-scoped
JSON each page fetches. Access is enforced by PatientSessionAuthMixin: every
request carries the authenticated patient id.

Most data is read from SDK models (visit list + AVS, profile, insurance). Lab,
imaging and letter documents - and the visit "View Note" PDF - are
DocumentReferences served as rendered PDFs through the FHIR document proxy
(needs CLIENT_ID / CLIENT_SECRET), since the SDK does not expose the PDF.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from logger import log

from portal_content.content_types.coverage import list_coverages
from portal_content.content_types.demographics import get_demographics
from portal_content.content_types.documents import list_documents
from portal_content.content_types.reviews import filter_reviewed
from portal_content.content_types.visits import (
    get_note_document,
    get_note_types_filter,
    list_notes,
    render_avs,
)
from portal_content.shared.config import hold_unreviewed_results, is_component_enabled
from portal_content.shared.fhir_documents import DocumentFetchError, fetch_document_content

# Components served as FHIR DocumentReference PDFs.
DOCUMENT_COMPONENTS = {"labs", "imaging", "letters"}


class PortalContentAPI(PatientSessionAuthMixin, SimpleAPI):
    """Patient-authenticated endpoints for the portal pages and their data."""

    PREFIX = "/app"

    # ----------------------------------------------------------------- helpers

    @property
    def _patient_id(self) -> str:
        return str(self.request.headers["canvas-logged-in-user-id"])

    def _fhir_credentials(self) -> tuple[str, str, str] | None:
        """(host, client_id, client_secret) or None if not configured."""
        client_id = self.secrets.get("CLIENT_ID", "")
        client_secret = self.secrets.get("CLIENT_SECRET", "")
        if not client_id or not client_secret:
            log.error("Document viewing requires CLIENT_ID and CLIENT_SECRET to be configured")
            return None
        return self.environment.get("CUSTOMER_IDENTIFIER", ""), client_id, client_secret

    def _success(self, data: Any) -> list[Response | Effect]:
        return [JSONResponse({"status": "success", "data": data}, status_code=HTTPStatus.OK)]

    def _error(self, message: str, status: HTTPStatus) -> list[Response | Effect]:
        return [JSONResponse({"status": "error", "message": message}, status_code=status)]

    def _page_params(self) -> tuple[int, int]:
        limit = min(int(self.request.query_params.get("limit") or 20), 50)
        offset = int(self.request.query_params.get("offset") or 0)
        return limit, offset

    @staticmethod
    def _valid_id(value: str) -> bool:
        return bool(value) and all(c.isalnum() or c in "-_" for c in value)

    # ------------------------------------------------------------------- pages

    @api.get("/records")
    def records_page(self) -> list[Response | Effect]:
        return [HTMLResponse(render_to_string("templates/records.html", {}), status_code=HTTPStatus.OK)]

    @api.get("/profile")
    def profile_page(self) -> list[Response | Effect]:
        return [HTMLResponse(render_to_string("templates/profile.html", {}), status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------- visit data

    @api.get("/visits")
    def visits_list(self) -> list[Response | Effect]:
        if not is_component_enabled("visits", self.secrets):
            return self._error("Visit notes are not enabled.", HTTPStatus.FORBIDDEN)
        note_types = get_note_types_filter(self.secrets)
        if not note_types:
            # Fail closed: with no NOTE_TYPES configured, no notes are eligible.
            return self._success({"summaries": [], "total": 0, "limit": 0, "offset": 0, "has_more": False})
        limit, offset = self._page_params()
        return self._success(list_notes(self._patient_id, note_types, limit, offset))

    @api.get("/visit-avs")
    def visit_avs(self) -> list[Response | Effect]:
        if not is_component_enabled("visits", self.secrets):
            return self._error("Visit notes are not enabled.", HTTPStatus.FORBIDDEN)
        note_id = self.request.query_params.get("note_id", "")
        if not self._valid_id(note_id):
            return self._error("Invalid note_id.", HTTPStatus.BAD_REQUEST)
        note_types = get_note_types_filter(self.secrets)
        avs_html = render_avs(self._patient_id, note_id, note_types)
        if avs_html is None:
            return self._error("Visit summary not available.", HTTPStatus.NOT_FOUND)
        return self._success({"avs_html": avs_html})

    @api.get("/visit-note")
    def visit_note(self) -> list[Response | Effect]:
        if not is_component_enabled("visits", self.secrets):
            return self._error("Visit notes are not enabled.", HTTPStatus.FORBIDDEN)
        note_id = self.request.query_params.get("note_id", "")
        if not self._valid_id(note_id):
            return self._error("Invalid note_id.", HTTPStatus.BAD_REQUEST)
        note_types = get_note_types_filter(self.secrets)
        document = get_note_document(self._patient_id, note_id, note_types)
        if document is None:
            return self._error("Visit note document not available.", HTTPStatus.NOT_FOUND)
        return self._success(document)

    # --------------------------------------------------- document data + files

    @api.get("/documents")
    def documents_list(self) -> list[Response | Effect]:
        component = self.request.query_params.get("component", "")
        if component not in DOCUMENT_COMPONENTS:
            return self._error("Unknown document type.", HTTPStatus.BAD_REQUEST)
        if not is_component_enabled(component, self.secrets):
            return self._error(f"{component} is not enabled.", HTTPStatus.FORBIDDEN)
        creds = self._fhir_credentials()
        if creds is None:
            return self._error("Document viewing is not configured.", HTTPStatus.INTERNAL_SERVER_ERROR)
        host, client_id, client_secret = creds
        try:
            reports = list_documents(host, client_id, client_secret, self._patient_id, component)
        except DocumentFetchError:
            return self._error("Unable to load documents.", HTTPStatus.BAD_GATEWAY)
        if hold_unreviewed_results(self.secrets) and component in ("labs", "imaging"):
            reports = filter_reviewed(reports, component, self._patient_id)
        for report in reports:
            report.pop("diagnostic_report_id", None)
        return self._success({"reports": reports})

    @api.get("/document")
    def document(self) -> list[Response | Effect]:
        """Stream a document PDF the patient owns.

        Ownership is enforced by the patient-scoped FHIR token plus a subject
        check inside the FHIR client. (The SDK is not used for ownership here
        because lab/imaging DocumentReferences are FHIR-synthesized and absent
        from the SDK data tables.)
        """
        ref_id = self.request.query_params.get("ref_id", "")
        if not self._valid_id(ref_id):
            return self._error("Invalid document id.", HTTPStatus.BAD_REQUEST)
        creds = self._fhir_credentials()
        if creds is None:
            return self._error("Document viewing is not configured.", HTTPStatus.INTERNAL_SERVER_ERROR)
        host, client_id, client_secret = creds
        try:
            content, content_type = fetch_document_content(
                host, client_id, client_secret, self._patient_id, ref_id
            )
        except DocumentFetchError:
            # Render a readable message inside the viewer iframe rather than a
            # blank PDF pane (e.g. a document with no Canvas-stored file).
            return [
                HTMLResponse(
                    "<!DOCTYPE html><html><body style='font-family:-apple-system,BlinkMacSystemFont,"
                    "Segoe UI,Roboto,sans-serif;padding:40px;color:#7f8c8d;text-align:center'>"
                    "<p>This document isn't available to view in the portal.</p></body></html>",
                    status_code=HTTPStatus.OK,
                )
            ]
        return [Response(content=content, status_code=HTTPStatus.OK, content_type=content_type)]

    # --------------------------------------------------------- profile data

    @api.get("/profile-info")
    def profile_info(self) -> list[Response | Effect]:
        info = get_demographics(self._patient_id)
        if info is None:
            return self._error("Profile not found.", HTTPStatus.NOT_FOUND)
        return self._success(info)

    @api.get("/profile-coverage")
    def profile_coverage(self) -> list[Response | Effect]:
        return self._success({"coverages": list_coverages(self._patient_id)})
