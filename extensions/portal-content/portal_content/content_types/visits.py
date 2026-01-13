"""Visits content type - visit notes portal."""

from http import HTTPStatus

import requests

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.v1.data.note import Note
from logger import log
from portal_content.shared.fhir_client import FHIRClient

# FHIR category for clinical notes
FHIR_CATEGORY = "clinical-note"
CONTENT_TYPE = "visits"

# Finalized note states
FINALIZED_STATES = ["SGN", "LKD", "RLK", "DSC"]

# HTML template
PORTAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Visit Notes</title>
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
        .notes-list { list-style: none; }
        .note-card { background-color: #fff; border: 1px solid #e1e8ed; border-radius: 8px; padding: 20px; margin-bottom: 15px; cursor: pointer; transition: all 0.2s ease; }
        .note-card:hover { border-color: #3498db; box-shadow: 0 2px 8px rgba(52, 152, 219, 0.2); }
        .note-date { font-size: 18px; font-weight: 600; color: #2c3e50; }
        .note-provider { color: #7f8c8d; font-size: 14px; margin: 8px 0; }
        .note-concern { color: #555; font-size: 15px; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; overflow-y: auto; }
        .modal.active { display: block; }
        .modal-content { background: white; max-width: 1400px; width: 95%; margin: 20px auto; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); height: calc(100vh - 40px); display: flex; flex-direction: column; }
        .modal-header { padding: 20px 30px; border-bottom: 1px solid #e1e8ed; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
        .modal-title { font-size: 24px; color: #2c3e50; }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: 500; }
        .btn-primary { background-color: #3498db; color: white; margin-right: 10px; }
        .btn-secondary { background-color: #95a5a6; color: white; }
        .modal-body { padding: 0; flex: 1; overflow: hidden; }
        .summary-section { margin-bottom: 30px; }
        .section-title { font-size: 18px; font-weight: 600; color: #2c3e50; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid #3498db; }
        .section-content { color: #555; line-height: 1.8; white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="container">
        <h1>My Visit Notes</h1>
        <p class="subtitle">View summaries of your recent healthcare visits</p>
        <div id="error-message" class="error" style="display: none;"></div>
        <div id="loading" class="loading">Loading your visit notes...</div>
        <div id="empty-state" class="empty-state" style="display: none;">
            <div class="empty-state-icon">📋</div>
            <h2>No Visit Notes Yet</h2>
            <p>Your visit summaries will appear here after your healthcare provider completes and locks your visit notes.</p>
        </div>
        <ul id="notes-list" class="notes-list" style="display: none;"></ul>
        <div id="load-more-container" style="text-align: center; margin-top: 20px; display: none;">
            <button id="load-more-btn" class="btn btn-primary" onclick="loadMoreNotes()">Load More</button>
        </div>
    </div>
    <div id="note-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="modal-title" id="modal-title">Visit Summary</h2>
                <div>
                    <button class="btn btn-secondary" onclick="closeModal()">Close</button>
                </div>
            </div>
            <div class="modal-body" id="modal-body"></div>
        </div>
    </div>
    <script>
        const API_ENDPOINT = '/plugin-io/api/portal_content/visits/notes';
        let currentNotes = [], currentOffset = 0, hasMore = false;
        const LIMIT = 20;
        document.addEventListener('DOMContentLoaded', loadNotes);
        async function loadNotes(append = false) {
            console.log('Loading notes...');
            const loading = document.getElementById('loading'), loadMoreBtn = document.getElementById('load-more-btn');
            if (!append) loading.style.display = 'block'; else { loadMoreBtn.disabled = true; loadMoreBtn.textContent = 'Loading...'; }
            try {
                const response = await fetch(API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'list', limit: LIMIT, offset: currentOffset }) });
                console.log('Response:', response.status);
                const result = await response.json();
                console.log('Data:', result);
                if (result.status === 'success') {
                    if (append) currentNotes = currentNotes.concat(result.data.summaries); else currentNotes = result.data.summaries;
                    hasMore = result.data.has_more || false;
                    currentOffset += result.data.summaries.length;
                    renderNotesList(currentNotes);
                    updateLoadMoreButton();
                } else showError(result.message || 'Failed to load notes');
            } catch (error) { console.error('Error:', error); showError('Network error: ' + error.message); }
            finally { loading.style.display = 'none'; if (append) { loadMoreBtn.disabled = false; loadMoreBtn.textContent = 'Load More'; } }
        }
        function loadMoreNotes() { loadNotes(true); }
        function updateLoadMoreButton() { document.getElementById('load-more-container').style.display = hasMore && currentNotes.length > 0 ? 'block' : 'none'; }
        function renderNotesList(notes) {
            const loading = document.getElementById('loading'), emptyState = document.getElementById('empty-state'), notesList = document.getElementById('notes-list');
            loading.style.display = 'none';
            if (notes.length === 0) { emptyState.style.display = 'block'; notesList.style.display = 'none'; return; }
            emptyState.style.display = 'none'; notesList.style.display = 'block';
            notesList.innerHTML = notes.map(note => `<li class="note-card" onclick="showNoteDetail('${note.note_id}')"><div class="note-date">${note.visit_type ? escapeHtml(note.visit_type) + ' on ' : ''}${formatDate(note.visit_date)}</div><div class="note-provider">With ${escapeHtml(note.provider_name)}</div>${note.chief_concern ? `<div class="note-concern">${escapeHtml(note.chief_concern)}</div>` : ''}</li>`).join('');
        }
        async function showNoteDetail(noteId) {
            console.log('Loading detail:', noteId);
            try {
                const response = await fetch(API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'detail', note_id: noteId }) });
                const result = await response.json();
                if (result.status === 'success') renderNoteDetail(result.data); else showError(result.message || 'Failed to load details');
            } catch (error) { showError('Network error: ' + error.message); }
        }
        function renderNoteDetail(note) {
            const modal = document.getElementById('note-modal'), modalTitle = document.getElementById('modal-title'), modalBody = document.getElementById('modal-body');
            modalTitle.textContent = `Visit Summary - ${formatDate(note.visit_date)}`;
            let html = '';
            if (note.document_url && note.document_type === 'pdf') {
                html = `<div style="width: 100%; height: 100%;">
                    <iframe src="${note.document_url}#pagemode=none&view=FitH" style="width: 100%; height: 100%; border: none;" title="Visit Note PDF"></iframe>
                </div>`;
            } else {
                html = `<div style="padding: 30px; overflow-y: auto; height: 100%;">`;
                html += `<div class="summary-section"><div class="section-title">Visit Information</div><div class="section-content"><strong>Provider:</strong> ${escapeHtml(note.provider_name)}<br><strong>Date:</strong> ${formatDate(note.visit_date)}</div></div>`;
                if (note.chief_concern) html += `<div class="summary-section"><div class="section-title">Reason for Visit</div><div class="section-content">${escapeHtml(note.chief_concern)}</div></div>`;
                if (note.assessment_and_plan) html += `<div class="summary-section"><div class="section-title">Assessment & Plan</div><div class="section-content">${escapeHtml(note.assessment_and_plan)}</div></div>`;
                if (note.follow_up) html += `<div class="summary-section"><div class="section-title">Follow-Up</div><div class="section-content">${escapeHtml(note.follow_up)}</div></div>`;
                html += `</div>`;
            }
            modalBody.innerHTML = html;
            modal.classList.add('active');
        }
        function closeModal() { document.getElementById('note-modal').classList.remove('active'); }
        function formatDate(dateString) { const date = new Date(dateString); return date.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }); }
        function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }
        function showError(message) { document.getElementById('loading').style.display = 'none'; const errorEl = document.getElementById('error-message'); errorEl.textContent = message; errorEl.style.display = 'block'; }
        document.getElementById('note-modal').addEventListener('click', function(e) { if (e.target === this) closeModal(); });
    </script>
</body>
</html>"""


def serve_portal_page(api: "PortalContentAPI") -> list[Response | Effect]:
    """Serve the visits portal HTML page."""
    patient_id = api.request.headers.get("canvas-logged-in-user-id")
    log.info(f"Serving visits portal page to patient: {patient_id}")

    return [
        HTMLResponse(
            PORTAL_HTML,
            status_code=HTTPStatus.OK,
        )
    ]


def handle_notes_request(api: "PortalContentAPI") -> list[Response | Effect]:
    """Route API requests for listing and fetching note details."""
    patient_id = api.request.headers.get("canvas-logged-in-user-id")
    log.info(f"Visits API request from patient: {patient_id}")

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
                {"status": "error", "message": str(e)},
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

    log.info(f"Proxying visit PDF {document_id} for patient: {patient_id}")

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
                {"status": "error", "message": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ]


def _get_note_types_filter(api: "PortalContentAPI") -> list[str] | None:
    """Get configured note types filter from plugin secrets."""
    try:
        note_types_config = api.secrets.get("NOTE_TYPES", "")
        if not note_types_config:
            return None
        allowed_types = [nt.strip() for nt in note_types_config.split(",") if nt.strip()]
        return allowed_types if allowed_types else None
    except Exception as e:
        log.error(f"Error parsing NOTE_TYPES config: {e}")
        return None


def _handle_list(api: "PortalContentAPI", patient_id: str, body: dict) -> list[Response | Effect]:
    """Handle listing notes for the patient."""
    try:
        limit = min(int(body.get("limit", 20)), 50)
        offset = int(body.get("offset", 0))

        note_types_filter = _get_note_types_filter(api)

        all_patient_notes = Note.objects.filter(patient__id=patient_id).select_related(
            "note_type_version", "provider", "current_state"
        ).order_by("-created")

        notes_query = all_patient_notes
        if note_types_filter:
            notes_query = notes_query.filter(note_type_version__code__in=note_types_filter)

        all_notes = list(notes_query)

        finalized_notes = []
        for note in all_notes:
            try:
                current_state_event = note.current_state
                if current_state_event and current_state_event.state in FINALIZED_STATES:
                    finalized_notes.append(note)
            except Exception as e:
                log.warning(f"Error checking state for note {note.id}: {e}")

        total_count = len(finalized_notes)
        notes = finalized_notes[offset : offset + limit]

        log.info(f"Found {total_count} finalized notes for patient {patient_id}")

        summaries = []
        for note in notes:
            try:
                summary = _extract_note_list_info(note)
                summaries.append(summary)
            except Exception as e:
                log.error(f"Error extracting summary for note {note.id}: {e}")

        return [
            JSONResponse(
                {
                    "status": "success",
                    "data": {
                        "summaries": summaries,
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
        log.error(f"Error listing notes: {e}", exc_info=True)
        return [
            JSONResponse(
                {"status": "error", "message": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ]


def _handle_detail(api: "PortalContentAPI", patient_id: str, body: dict) -> list[Response | Effect]:
    """Handle fetching detailed note information."""
    try:
        note_id = body.get("note_id")
        if not note_id:
            return [
                JSONResponse(
                    {"status": "error", "message": "note_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            note = Note.objects.select_related(
                "note_type_version", "provider", "current_state", "patient"
            ).get(id=note_id)
        except Note.DoesNotExist:
            return [
                JSONResponse(
                    {"status": "error", "message": "Note not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        note_patient_id = str(note.patient.id) if hasattr(note, "patient") and note.patient else None
        if note_patient_id != str(patient_id):
            log.error(
                f"SECURITY: Patient {patient_id} attempted to access note {note_id} belonging to patient {note_patient_id}"
            )
            return [
                JSONResponse(
                    {"status": "error", "message": "Access denied"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        current_state_event = note.current_state

        if not current_state_event:
            log.warning(f"Access denied: Note {note_id} has no current state")
            return [
                JSONResponse(
                    {"status": "error", "message": "Note not available yet"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        state_code = current_state_event.state

        if state_code not in FINALIZED_STATES:
            log.warning(f"Access denied: Note {note_id} is not finalized (state: {state_code})")
            return [
                JSONResponse(
                    {"status": "error", "message": "Note not available yet"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        fhir_client = api._get_fhir_client(patient_id)
        if not fhir_client:
            log.error("FHIR client not available - falling back to command extraction")
            summary = _extract_note_summary(note)
        else:
            encounter_id = None
            if hasattr(note, "encounter") and note.encounter:
                encounter_id = str(note.encounter.id) if hasattr(note.encounter, "id") else None

            bundle = fhir_client.search_document_references(
                patient_id=patient_id, status="current", category=FHIR_CATEGORY, encounter=encounter_id
            )

            matching_doc = None
            entries = bundle.get("entry", [])

            for entry in entries:
                resource = entry.get("resource", {})
                context = resource.get("context", {})
                context_encounter = context.get("encounter", [])

                if encounter_id and context_encounter:
                    for enc_ref in context_encounter:
                        enc_ref_id = enc_ref.get("reference", "")
                        if encounter_id in enc_ref_id:
                            matching_doc = resource
                            break

                if not matching_doc and not encounter_id:
                    matching_doc = resource

                if matching_doc:
                    break

            if matching_doc:
                document_id = matching_doc.get("id")
                proxy_url = f"/plugin-io/api/portal_content/visits/pdf?document_id={document_id}"

                summary = {
                    "note_id": str(note.id),
                    "visit_date": note.created.isoformat() if hasattr(note, "created") else None,
                    "provider_name": _extract_provider_name(note),
                    "document_reference_id": document_id,
                    "document_url": proxy_url,
                    "document_type": "pdf",
                }
            else:
                log.warning(f"No matching DocumentReference found for note {note_id}, encounter {encounter_id}")
                summary = _extract_note_summary(note)

        return [
            JSONResponse(
                {"status": "success", "data": summary},
                status_code=HTTPStatus.OK,
            )
        ]
    except Exception as e:
        log.error(f"Error getting note detail: {e}", exc_info=True)
        return [
            JSONResponse(
                {"status": "error", "message": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ]


def _extract_note_list_info(note) -> dict:
    """Extract minimal info for list view."""
    visit_type = None
    if hasattr(note, "note_type_version") and note.note_type_version:
        visit_type = getattr(note.note_type_version, "name", None)

    return {
        "note_id": str(note.id),
        "visit_date": note.created.isoformat() if hasattr(note, "created") else None,
        "visit_type": visit_type,
        "provider_name": _extract_provider_name(note),
        "chief_concern": _extract_chief_concern(note),
    }


def _extract_note_summary(note) -> dict:
    """Extract full note summary by parsing all command types."""
    chief_concern = None
    diagnoses = []
    narratives = []
    prescriptions = []
    goals = []
    instructions = []
    follow_up_text = None

    if hasattr(note, "commands"):
        commands_list = list(note.commands.all())
        for cmd in commands_list:
            if not hasattr(cmd, "data") or not cmd.data:
                continue

            data = cmd.data

            try:
                if "comment" in data and data.get("comment"):
                    if not chief_concern:
                        chief_concern = data["comment"]

                if "diagnose" in data:
                    dx = data["diagnose"]
                    dx_text = dx.get("text", "") if isinstance(dx, dict) else str(dx)
                    background = data.get("background", "")
                    assessment = data.get("today_assessment", "")

                    dx_parts = [dx_text]
                    if background:
                        dx_parts.append(f"Background: {background}")
                    if assessment:
                        dx_parts.append(f"Assessment: {assessment}")
                    diagnoses.append("\n".join(dx_parts))

                if "narrative" in data and data.get("narrative"):
                    narratives.append(data["narrative"])

                if "prescribe" in data:
                    rx = data["prescribe"]
                    rx_text = rx.get("text", "") if isinstance(rx, dict) else str(rx)
                    sig = data.get("sig", "")
                    refills = data.get("refills", "")

                    rx_str = rx_text
                    if sig:
                        rx_str += f" - {sig}"
                    if refills:
                        rx_str += f" ({refills} refills)"
                    prescriptions.append(rx_str)

                if "goal_statement" in data:
                    goal = data["goal_statement"]
                    due_date = data.get("due_date", "")

                    goal_str = goal
                    if due_date:
                        goal_str += f" (Due: {due_date})"
                    goals.append(goal_str)

                if "instruct" in data:
                    inst = data["instruct"]
                    inst_title = inst.get("text", "") if isinstance(inst, dict) else str(inst)
                    inst_narrative = data.get("narrative", "")

                    inst_str = inst_title
                    if inst_narrative:
                        inst_str += f":\n{inst_narrative}"
                    instructions.append(inst_str)

                if "requested_date" in data:
                    req_date = data["requested_date"]
                    date_str = req_date.get("date", "") if isinstance(req_date, dict) else str(req_date)
                    note_type = data.get("note_type", {})
                    note_type_text = note_type.get("text", "") if isinstance(note_type, dict) else ""

                    follow_up_text = f"Follow-up {note_type_text} appointment on {date_str}"

            except Exception as e:
                log.warning(f"Error parsing command data: {e}")

    plan_parts = []
    if diagnoses:
        plan_parts.append("DIAGNOSES:\n" + "\n\n".join(diagnoses))
    if narratives:
        plan_parts.append("NOTES:\n" + "\n\n".join(narratives))
    if prescriptions:
        plan_parts.append("MEDICATIONS:\n" + "\n".join(f"• {rx}" for rx in prescriptions))
    if goals:
        plan_parts.append("GOALS:\n" + "\n".join(f"• {goal}" for goal in goals))
    if instructions:
        plan_parts.append("INSTRUCTIONS:\n" + "\n\n".join(instructions))

    assessment_and_plan = "\n\n".join(plan_parts) if plan_parts else None

    return {
        "note_id": str(note.id),
        "visit_date": note.created.isoformat() if hasattr(note, "created") else None,
        "provider_name": _extract_provider_name(note),
        "chief_concern": chief_concern,
        "assessment_and_plan": assessment_and_plan,
        "follow_up": follow_up_text,
    }


def _extract_provider_name(note) -> str:
    """Extract provider name from note."""
    try:
        if hasattr(note, "provider") and note.provider:
            if hasattr(note.provider, "full_name"):
                return note.provider.full_name
            elif hasattr(note.provider, "first_name") and hasattr(note.provider, "last_name"):
                return f"Dr. {note.provider.first_name} {note.provider.last_name}"
        return "Unknown Provider"
    except Exception:
        return "Unknown Provider"


def _extract_chief_concern(note) -> str:
    """Extract chief concern from note."""
    try:
        if hasattr(note, "chief_complaint") and note.chief_complaint:
            return note.chief_complaint
        return ""
    except Exception:
        return ""
