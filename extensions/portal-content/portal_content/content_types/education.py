"""Education content type - educational materials portal."""

from http import HTTPStatus

import requests

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from logger import log
from portal_content.shared.fhir_client import FHIRClient

# FHIR category for educational materials
FHIR_CATEGORY = "educationalmaterial"
DEFAULT_REPORT_NAME = "Educational Material"
CONTENT_TYPE = "education"

# HTML template
PORTAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Learning Materials</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f5f5f5; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #7f8c8d; margin-bottom: 30px; font-size: 16px; }
        .loading { text-align: center; padding: 40px; color: #7f8c8d; }
        .error { background-color: #fee; color: #c33; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
        .empty-state { text-align: center; padding: 60px 20px; color: #7f8c8d; }
        .empty-state-icon { font-size: 48px; margin-bottom: 20px; }
        .reports-list { list-style: none; }
        .report-card { background-color: #fff; border: 1px solid #e1e8ed; border-radius: 8px; padding: 20px; margin-bottom: 15px; cursor: pointer; transition: all 0.2s ease; }
        .report-card:hover { border-color: #3498db; box-shadow: 0 2px 8px rgba(52, 152, 219, 0.2); }
        .report-name { font-size: 18px; font-weight: 600; color: #2c3e50; margin-bottom: 8px; }
        .report-dates { color: #7f8c8d; font-size: 14px; }
        .report-date-item { display: inline-block; margin-right: 20px; }
        .date-label { font-weight: 500; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; overflow-y: auto; }
        .modal.active { display: block; }
        .modal-content { background: white; max-width: 1400px; width: 95%; margin: 20px auto; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); height: calc(100vh - 40px); display: flex; flex-direction: column; }
        .modal-header { padding: 20px 30px; border-bottom: 1px solid #e1e8ed; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
        .modal-title { font-size: 24px; color: #2c3e50; }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: 500; }
        .btn-primary { background-color: #3498db; color: white; margin-right: 10px; }
        .btn-secondary { background-color: #95a5a6; color: white; }
        .modal-body { padding: 0; flex: 1; overflow: hidden; }
    </style>
</head>
<body>
    <div class="container">
        <h1>My Learning Materials</h1>
        <p class="subtitle">View educational materials shared by your care team</p>
        <div id="error-message" class="error" style="display: none;"></div>
        <div id="loading" class="loading">Loading your educational materials...</div>
        <div id="empty-state" class="empty-state" style="display: none;">
            <div class="empty-state-icon">📚</div>
            <h2>No Educational Materials Yet</h2>
            <p>Educational materials shared by your providers will appear here.</p>
        </div>
        <ul id="reports-list" class="reports-list" style="display: none;"></ul>
        <div id="load-more-container" style="text-align: center; margin-top: 20px; display: none;">
            <button id="load-more-btn" class="btn btn-primary" onclick="loadMoreReports()">Load More</button>
        </div>
    </div>
    <div id="report-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="modal-title" id="modal-title">Educational Material</h2>
                <div>
                    <button class="btn btn-secondary" onclick="closeModal()">Close</button>
                </div>
            </div>
            <div class="modal-body" id="modal-body"></div>
        </div>
    </div>
    <script>
        const API_ENDPOINT = '/plugin-io/api/portal_content/education/reports';
        let currentReports = [], currentOffset = 0, hasMore = false;
        const LIMIT = 20;
        document.addEventListener('DOMContentLoaded', loadReports);
        async function loadReports(append = false) {
            console.log('Loading reports...');
            const loading = document.getElementById('loading'), loadMoreBtn = document.getElementById('load-more-btn');
            if (!append) loading.style.display = 'block'; else { loadMoreBtn.disabled = true; loadMoreBtn.textContent = 'Loading...'; }
            try {
                const response = await fetch(API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'list', limit: LIMIT, offset: currentOffset }) });
                console.log('Response:', response.status);
                const result = await response.json();
                console.log('Data:', result);
                if (result.status === 'success') {
                    if (append) currentReports = currentReports.concat(result.data.reports); else currentReports = result.data.reports;
                    hasMore = result.data.has_more || false;
                    currentOffset += result.data.reports.length;
                    renderReportsList(currentReports);
                    updateLoadMoreButton();
                } else showError(result.message || 'Failed to load reports');
            } catch (error) { console.error('Error:', error); showError('We\\'re having trouble loading your materials. Please try again later.'); }
            finally { loading.style.display = 'none'; if (append) { loadMoreBtn.disabled = false; loadMoreBtn.textContent = 'Load More'; } }
        }
        function loadMoreReports() { loadReports(true); }
        function updateLoadMoreButton() { document.getElementById('load-more-container').style.display = hasMore && currentReports.length > 0 ? 'block' : 'none'; }
        function renderReportsList(reports) {
            const loading = document.getElementById('loading'), emptyState = document.getElementById('empty-state'), reportsList = document.getElementById('reports-list');
            loading.style.display = 'none';
            if (reports.length === 0) { emptyState.style.display = 'block'; reportsList.style.display = 'none'; return; }
            emptyState.style.display = 'none'; reportsList.style.display = 'block';
            reportsList.innerHTML = reports.map(report => `<li class="report-card" onclick="showReportDetail('${report.report_id}')"><div class="report-name">${escapeHtml(report.report_name)}</div><div class="report-dates">${report.date_collected ? `<span class="report-date-item"><span class="date-label">Collected:</span> ${formatDate(report.date_collected)}</span>` : ''}<span class="report-date-item"><span class="date-label">Received:</span> ${formatDate(report.date_received)}</span></div></li>`).join('');
        }
        async function showReportDetail(reportId) {
            console.log('Loading detail:', reportId);
            try {
                const response = await fetch(API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'detail', report_id: reportId }) });
                const result = await response.json();
                if (result.status === 'success') renderReportDetail(result.data); else showError(result.message || 'Failed to load details');
            } catch (error) { console.error('Error:', error); showError('We\\'re having trouble loading this material. Please try again later.'); }
        }
        function renderReportDetail(report) {
            const modal = document.getElementById('report-modal'), modalTitle = document.getElementById('modal-title'), modalBody = document.getElementById('modal-body');
            modalTitle.textContent = `${report.report_name} - ${formatDate(report.date_received)}`;
            let html = '';
            if (report.pdf_url) {
                html = `<div style="width: 100%; height: 100%;">
                    <iframe src="${report.pdf_url}#pagemode=none&view=FitH" style="width: 100%; height: 100%; border: none;" title="Educational Material PDF"></iframe>
                </div>`;
            } else {
                html = `<div style="padding: 30px; overflow-y: auto; height: 100%;"><p>Educational material not available.</p></div>`;
            }
            modalBody.innerHTML = html;
            modal.classList.add('active');
        }
        function closeModal() { document.getElementById('report-modal').classList.remove('active'); }
        function formatDate(dateString) { const date = new Date(dateString); return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }); }
        function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }
        function showError(message) { document.getElementById('loading').style.display = 'none'; const errorEl = document.getElementById('error-message'); errorEl.textContent = message; errorEl.style.display = 'block'; }
        document.getElementById('report-modal').addEventListener('click', function(e) { if (e.target === this) closeModal(); });
    </script>
</body>
</html>"""


def serve_portal_page(api: "PortalContentAPI") -> list[Response | Effect]:
    """Serve the education portal HTML page."""
    patient_id = api.request.headers.get("canvas-logged-in-user-id")
    log.info(f"Serving education portal page to patient: {patient_id}")

    return [
        HTMLResponse(
            PORTAL_HTML,
            status_code=HTTPStatus.OK,
        )
    ]


def handle_reports_request(api: "PortalContentAPI") -> list[Response | Effect]:
    """Route API requests for listing and fetching report details."""
    patient_id = api.request.headers.get("canvas-logged-in-user-id")
    log.info(f"Education API request from patient: {patient_id}")

    try:
        body = api.request.json()
        action = body.get("action")
        log.info(f"Action: {action}")

        if action == "list":
            return _handle_list(api, patient_id, body)
        elif action == "detail":
            return _handle_detail(api, patient_id, body)
        else:
            return [
                JSONResponse(
                    {"status": "error", "message": f"Unknown action: {action}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

    except Exception as e:
        log.error(f"Error handling request: {e}", exc_info=True)
        return [
            JSONResponse(
                {"status": "error", "message": "We encountered an issue loading your materials. Please try again later."},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ]


def proxy_pdf(api: "PortalContentAPI") -> list[Response | Effect]:
    """Proxy PDF download from FHIR API with authentication."""
    patient_id = api.request.headers.get("canvas-logged-in-user-id")

    document_id = api.request.query_params.get("document_id")
    if not document_id:
        return [
            JSONResponse(
                {"status": "error", "message": "document_id parameter required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        ]

    log.info(f"Proxying education PDF {document_id} for patient: {patient_id}")

    try:
        fhir_client = api._get_fhir_client(patient_id)
        if not fhir_client:
            log.error("FHIR client not available for PDF proxy")
            return [
                JSONResponse(
                    {"status": "error", "message": "Unable to retrieve document"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        # Verify document ownership
        doc_ref_url = f"{fhir_client.base_url}/DocumentReference/{document_id}"
        log.info(f"Verifying document ownership: {doc_ref_url}")

        verify_response = requests.get(
            doc_ref_url,
            headers={"Authorization": f"Bearer {fhir_client.token}", "Accept": "application/json"},
        )

        if verify_response.status_code != 200:
            log.error(f"Failed to fetch DocumentReference metadata: {verify_response.status_code}")
            return [
                JSONResponse(
                    {"status": "error", "message": "Document not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        doc_ref = verify_response.json()
        subject = doc_ref.get("subject", {})
        subject_ref = subject.get("reference", "")
        doc_patient_id = subject_ref.replace("Patient/", "") if subject_ref.startswith("Patient/") else None

        if doc_patient_id != patient_id:
            log.error(
                f"SECURITY: Patient {patient_id} attempted to access PDF {document_id} belonging to patient {doc_patient_id}"
            )
            return [
                JSONResponse(
                    {"status": "error", "message": "Access denied"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        log.info(f"Document ownership verified for patient {patient_id}")

        pdf_url = f"{fhir_client.base_url}/DocumentReference/{document_id}/files/content"
        log.info(f"Fetching PDF from: {pdf_url}")

        response = requests.get(
            pdf_url,
            headers={"Authorization": f"Bearer {fhir_client.token}"},
        )

        if response.status_code != 200:
            log.error(f"Failed to fetch PDF: {response.status_code} - {response.text}")
            return [
                JSONResponse(
                    {"status": "error", "message": "Document not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        from canvas_sdk.effects.simple_api import Response as RawResponse

        return [
            RawResponse(
                content=response.content,
                status_code=HTTPStatus.OK,
                headers={"Content-Type": "application/pdf"},
            )
        ]

    except Exception as e:
        log.error(f"Error proxying PDF: {e}", exc_info=True)
        return [
            JSONResponse(
                {"status": "error", "message": "We encountered an issue retrieving this document. Please try again later."},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ]


def _handle_list(api: "PortalContentAPI", patient_id: str, body: dict) -> list[Response | Effect]:
    """Handle listing educational materials for the patient."""
    try:
        limit = min(int(body.get("limit", 20)), 50)
        offset = int(body.get("offset", 0))

        log.info(f"Listing educational materials for patient {patient_id}, limit={limit}, offset={offset}")

        fhir_client = api._get_fhir_client(patient_id)
        if not fhir_client:
            log.error("FHIR client not available")
            return [
                JSONResponse(
                    {"status": "error", "message": "Unable to retrieve educational materials"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        bundle = fhir_client.search_document_references(
            patient_id=patient_id, status="current", category=FHIR_CATEGORY
        )

        entries = bundle.get("entry", [])
        log.info(f"Found {len(entries)} DocumentReferences with category {FHIR_CATEGORY}")

        reports = []
        for entry in entries:
            try:
                resource = entry.get("resource", {})
                report_summary = _extract_report_summary(resource, patient_id)
                if report_summary:
                    reports.append(report_summary)
            except Exception as e:
                log.error(f"Error extracting report summary: {e}")

        reports.sort(key=lambda r: r.get("date_received", ""), reverse=True)

        total_count = len(reports)
        paginated_reports = reports[offset : offset + limit]

        return [
            JSONResponse(
                {
                    "status": "success",
                    "data": {
                        "reports": paginated_reports,
                        "total": total_count,
                        "limit": limit,
                        "offset": offset,
                        "has_more": (offset + limit) < total_count,
                    },
                },
                status_code=HTTPStatus.OK,
            )
        ]
    except Exception as e:
        log.error(f"Error listing reports: {e}", exc_info=True)
        return [
            JSONResponse(
                {"status": "error", "message": "We encountered an issue loading your materials. Please try again later."},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ]


def _handle_detail(api: "PortalContentAPI", patient_id: str, body: dict) -> list[Response | Effect]:
    """Handle fetching detailed report information."""
    try:
        report_id = body.get("report_id")
        if not report_id:
            return [
                JSONResponse(
                    {"status": "error", "message": "report_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(f"Getting detail for education report {report_id}")

        fhir_client = api._get_fhir_client(patient_id)
        if not fhir_client:
            log.error("FHIR client not available")
            return [
                JSONResponse(
                    {"status": "error", "message": "Unable to retrieve educational material"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        report_url = f"{fhir_client.base_url}/DocumentReference/{report_id}"
        log.info(f"Fetching DocumentReference: {report_url}")

        response = requests.get(
            report_url,
            headers={"Authorization": f"Bearer {fhir_client.token}", "Accept": "application/json"},
        )

        if response.status_code != 200:
            log.error(f"Failed to fetch DocumentReference: {response.status_code}")
            return [
                JSONResponse(
                    {"status": "error", "message": "Report not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        document_reference = response.json()

        subject = document_reference.get("subject", {})
        subject_ref = subject.get("reference", "")
        report_patient_id = subject_ref.replace("Patient/", "") if subject_ref.startswith("Patient/") else None

        if report_patient_id != patient_id:
            log.error(
                f"SECURITY: Patient {patient_id} attempted to access report {report_id} belonging to patient {report_patient_id}"
            )
            return [
                JSONResponse(
                    {"status": "error", "message": "Access denied"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        report_detail = _extract_report_summary(document_reference, patient_id)

        return [
            JSONResponse(
                {"status": "success", "data": report_detail},
                status_code=HTTPStatus.OK,
            )
        ]
    except Exception as e:
        log.error(f"Error getting report detail: {e}", exc_info=True)
        return [
            JSONResponse(
                {"status": "error", "message": "We encountered an issue loading this material. Please try again later."},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ]


def _extract_report_summary(document_reference: dict, patient_id: str) -> dict | None:
    """Extract educational material summary from FHIR DocumentReference resource."""
    try:
        report_id = document_reference.get("id")

        report_name = document_reference.get("description", "")
        if not report_name:
            doc_type = document_reference.get("type", {})
            coding = doc_type.get("coding", [])
            report_name = doc_type.get("text", DEFAULT_REPORT_NAME)
            if not report_name and coding:
                report_name = coding[0].get("display", DEFAULT_REPORT_NAME)

        date_received = document_reference.get("date")
        date_collected = None
        context = document_reference.get("context", {})
        period = context.get("period", {})
        if period:
            date_collected = period.get("start")

        pdf_url = f"/plugin-io/api/portal_content/education/pdf?document_id={report_id}"

        return {
            "report_id": report_id,
            "patient_id": patient_id,
            "report_name": report_name,
            "date_collected": date_collected,
            "date_received": date_received,
            "pdf_url": pdf_url,
        }

    except Exception as e:
        log.error(f"Error extracting report summary: {e}")
        return None
