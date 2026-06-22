"""FHIR client for listing and streaming patient document content (PDFs).

Lab and imaging reports are exposed by the FHIR API as DocumentReferences (the
SDK data tables don't carry them) - each points at a rendered PDF
(DiagnosticReport presentedForm). Notes and letters are DocumentReferences too.
This module lists documents by category and streams their PDF bytes through the
plugin, because presigned S3 URLs need media credentials the instance may not
have. Uses canvas_sdk Http (not raw requests/httpx).

A patient-scoped token is used, so the FHIR API only returns the patient's own
documents; fetch additionally verifies the subject and that the content URL is
on the instance's own FHIR host (SSRF guard).
"""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import urlencode

from requests import RequestException  # type: ignore[import-untyped]

from canvas_sdk.utils.http import Http
from logger import log

_SCOPE = "patient/DocumentReference.read patient/DiagnosticReport.read"
_PROXY = "/plugin-io/api/portal_content/app/document"


class DocumentFetchError(Exception):
    """Raised when document data cannot be retrieved."""

    pass


def _fhir_host(host: str) -> str:
    return f"fumage-{host}.canvasmedical.com"


def _token(host: str, client_id: str, client_secret: str, patient_id: str) -> str:
    try:
        response = Http().post(
            f"https://{host}.canvasmedical.com/auth/token/",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": _SCOPE,
                "patient": patient_id,
            },
        )
    except RequestException as exc:
        log.error(f"Document token request error: {exc}")
        raise DocumentFetchError("Unable to reach the authorization server") from exc

    if response.status_code != HTTPStatus.OK:
        log.error(f"Document token request failed with status {response.status_code}")
        raise DocumentFetchError("Authorization failed")

    token = response.json().get("access_token")
    if not token:
        raise DocumentFetchError("Authorization response missing access token")
    return str(token)


def _authorized_get(url: str, token: str):  # type: ignore[no-untyped-def]
    try:
        return Http().get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    except RequestException as exc:
        log.error(f"FHIR request error: {exc}")
        raise DocumentFetchError("Unable to reach the document service") from exc


def search_documents(
    host: str, client_id: str, client_secret: str, patient_id: str, category: str
) -> list[dict]:
    """List the patient's current documents of a category, newest first."""
    token = _token(host, client_id, client_secret, patient_id)
    query = urlencode({"patient": patient_id, "category": category, "status": "current"})
    response = _authorized_get(f"https://{_fhir_host(host)}/DocumentReference?{query}", token)
    if response.status_code != HTTPStatus.OK:
        log.error(f"DocumentReference search failed with status {response.status_code}")
        raise DocumentFetchError("Unable to list documents")

    reports = []
    for entry in response.json().get("entry", []):
        resource = entry.get("resource", {})
        ref_id = resource.get("id")
        if not ref_id:
            continue
        # description is the specific report/material name (e.g. "Hemoglobin A1C");
        # type.text is only the generic category label ("Laboratory report").
        type_info = resource.get("type", {})
        name = resource.get("description") or type_info.get("text") or "Document"
        # For lab/imaging docs the content URL is /DiagnosticReport/{id}/...; capture
        # that id so review-gating can look up the linked report.
        attachment_url = (resource.get("content") or [{}])[0].get("attachment", {}).get("url", "") or ""
        diagnostic_report_id = None
        if "/DiagnosticReport/" in attachment_url:
            diagnostic_report_id = attachment_url.split("/DiagnosticReport/", 1)[1].split("/", 1)[0]
        reports.append(
            {
                "report_id": ref_id,
                "report_name": name,
                "date": resource.get("date"),
                "content_url": f"{_PROXY}?ref_id={ref_id}",
                "diagnostic_report_id": diagnostic_report_id,
            }
        )
    log.info(f"Found {len(reports)} {category} documents for patient {patient_id}")
    return reports


def fetch_document_content(
    host: str, client_id: str, client_secret: str, patient_id: str, reference_id: str
) -> tuple[bytes, str]:
    """Return (bytes, content_type) for a document the patient owns.

    Raises:
        DocumentFetchError: on auth/transport failure, ownership mismatch, or a
        non-200 response.
    """
    token = _token(host, client_id, client_secret, patient_id)

    meta = _authorized_get(f"https://{_fhir_host(host)}/DocumentReference/{reference_id}", token)
    if meta.status_code != HTTPStatus.OK:
        raise DocumentFetchError("Document not found")
    resource = meta.json()

    subject = resource.get("subject", {}).get("reference", "")
    if not subject.endswith(patient_id):
        log.warning(f"Patient {patient_id} requested document {reference_id} owned by {subject!r}")
        raise DocumentFetchError("Document not available")

    content = resource.get("content", [])
    attachment = content[0].get("attachment", {}) if content else {}
    content_type = attachment.get("contentType") or "application/pdf"

    # Fetch the document's own rendered file. This works for every type - POC
    # labs (whose DiagnosticReport presentedForm is empty because the PDF isn't
    # produced by data integration), sent-out labs, imaging, notes, and letters -
    # unlike the attachment's presentedForm URL, which 307s to nothing for POC.
    url = f"https://{_fhir_host(host)}/DocumentReference/{reference_id}/files/content"
    try:
        binary = Http().get(url, headers={"Authorization": f"Bearer {token}"})
    except RequestException as exc:
        log.error(f"Document content request error: {exc}")
        raise DocumentFetchError("Unable to retrieve the document") from exc
    if binary.status_code != HTTPStatus.OK:
        raise DocumentFetchError("Document content not found")

    content = bytes(binary.content)
    # Some DocumentReferences point at externally-hosted content with no
    # Canvas-stored file and return an error payload instead of a PDF. Don't pass
    # that off as a document.
    if "pdf" in content_type.lower() and not content.startswith(b"%PDF"):
        raise DocumentFetchError("Document content is not available")

    return content, str(content_type)
