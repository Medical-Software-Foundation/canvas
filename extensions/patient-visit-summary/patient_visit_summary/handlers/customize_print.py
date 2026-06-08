"""Customize & Print: ActionButton + SimpleAPI for customizable note printing.

Uses the shared NoteDataExtractor to fetch data, then transforms it into
a structure the customize_print.html template can consume — a list of
toggleable, reorderable command sections with pre-rendered print HTML.
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timezone
from hmac import compare_digest
from http import HTTPStatus
from typing import Any
from uuid import UUID

from requests import RequestException

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.handlers.simple_api import SimpleAPI, SessionCredentials, api, Credentials
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import Http
from canvas_sdk.utils.pdf import pdf_generator
from canvas_sdk.clients.canvas_fhir import CanvasFhir
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.document_reference import DocumentReference

from logger import log

from patient_visit_summary.models import CustomizedNotePrint
from patient_visit_summary.services.note_data_extractor import NoteDataExtractor
from patient_visit_summary.services.command_blocks import (
    enumerate_sections,
    render_blocks,
)

# Regenerated on every plugin (re)load so served HTML and its asset/modal URLs
# bust any stale browser cache.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class _CustomizePrintButtonBase(ActionButton):
    """Shared launcher for the Customize & Print modal.

    Two concrete buttons render this — one in the note footer (existing) and
    one in the note header (so it's reachable after the note is locked
    without scrolling down).
    """

    BUTTON_TITLE = "Customize & Print"

    def visible(self) -> bool:
        return True

    def handle(self) -> list[Effect]:
        log.info(f"Customize & Print clicked for patient {self.target}")
        # Resolve the note's external UUID so the dbid never appears in the URL.
        note = Note.objects.filter(dbid=self.event.context["note_id"]).first()
        note_uuid = note.id if note else ""
        return [
            LaunchModalEffect(
                url=(
                    f"/plugin-io/api/patient_visit_summary/customize/"
                    f"?patient_id={self.target}&note_id={note_uuid}&v={_CACHE_BUST}"
                ),
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="Customize & Print",
            ).apply()
        ]


class CustomizePrintButton(_CustomizePrintButtonBase):
    """Button in the note footer to customize and print a note."""

    BUTTON_KEY = "CUSTOMIZE_PRINT"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_FOOTER


class CustomizePrintHeaderButton(_CustomizePrintButtonBase):
    """Note-header twin of CustomizePrintButton — reachable on a locked note
    without scrolling to the footer."""

    BUTTON_KEY = "CUSTOMIZE_PRINT_HEADER"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER


def _compute_age(birth_date: Any) -> str:
    """Return integer age in years as a string, or '' if birth_date is unknown."""
    if not birth_date:
        return ""
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return str(years) if years >= 0 else ""


def build_customize_print_context(template_context: dict[str, Any]) -> dict[str, Any]:
    """Transform the shared template context into the structure needed by customize_print.html.

    Returns a dict with:
        - sections: list of {key, title, items: [{id, display, printHtml}]}
        - note_data_json: JSON string for embedding in the template
        - header info for the preview
    """
    patient = template_context["patient"]
    provider = template_context["provider"]
    provider_top_role = template_context.get("provider_top_role")

    # Build header data for the JS print preview
    provider_name = f"{provider.first_name} {provider.last_name}"
    if provider_top_role:
        provider_name += f", {provider_top_role.public_abbreviation}"

    practice = template_context.get("practice_location_info") or {}
    header = {
        "patientName": f"{patient.first_name} {patient.last_name}",
        "dob": str(patient.birth_date) if patient.birth_date else "",
        "sex": patient.sex_at_birth or "",
        "age": _compute_age(patient.birth_date),
        "providerName": provider_name,
        "dateOfService": template_context.get("appointment_date", ""),
        # Top-right of the printout header — clinic logo + address block
        # sourced from the note's practice location (mirrors what home-app's
        # standard note print renders).
        "clinicLogoUrl": practice.get("logo_url", ""),
        "clinicName": practice.get("name", ""),
        "clinicAddressLine1": practice.get("address_line1", ""),
        "clinicAddressLine2": practice.get("address_line2", ""),
        "clinicCity": practice.get("city", ""),
        "clinicStateCode": practice.get("state_code", ""),
        "clinicPostalCode": practice.get("postal_code", ""),
        "clinicPhone": practice.get("phone", ""),
        "clinicFax": practice.get("fax", ""),
    }

    # Walk the enumerated command groups and shape them into the sidebar tree
    # this UI needs. Each section becomes a `{key, title, items: [...]}`. Each
    # group with a single entry becomes a standalone sidebar item; groups with
    # multiple entries become a parent with children (one per entry).
    # `PINNED_SECTION_KEY` renders as its own block in both views and in print
    # — never flattened into the note-order list, never SOAP-grouped with others.
    PINNED_SECTION_KEY = "billing"
    sections = []
    pinned_section = None
    commands = []
    cmd_id = 0

    for section in enumerate_sections(template_context):
        section_items = []
        for group in section["groups"]:
            entries = group["entries"]
            display_name = group["display_name"]
            cmd_id += 1
            parent_id = f"cmd-{cmd_id}"

            is_pinned = section["key"] == PINNED_SECTION_KEY

            def _billing_table_row(entry: dict) -> dict | None:
                # The pinned billing section prints as a single multi-row
                # table in the preview (built by JS from these structured
                # rows). Non-billing commands don't get this — they keep
                # printHtml as-is.
                if not is_pinned:
                    return None
                raw = entry.get("raw") or {}
                return {
                    "code": raw.get("code") or "",
                    "cpt": raw.get("cpt") or "",
                    "description": raw.get("description") or "",
                    "units": raw.get("units"),
                    "modifiers": raw.get("modifiers") or [],
                    "diagnoses": raw.get("diagnoses") or [],
                }

            if len(entries) > 1:
                children = []
                for entry in entries:
                    cmd_id += 1
                    child_id = f"cmd-{cmd_id}"
                    children.append({"id": child_id, "display": entry["title"]})
                    metadata_blocks = entry.get("metadata_blocks") or []
                    cmd = {
                        "id": child_id,
                        "section": section["key"],
                        "displayText": display_name,
                        # Leaf label for the flat (note-order) list — the per-entry
                        # title, so distinct entries of the same command type differ.
                        "label": entry["title"],
                        "printHtml": render_blocks(entry["blocks"]),
                        # Rendered separately so the modal's "Include command
                        # metadata" toggle can append it without re-fetching.
                        "metadataHtml": render_blocks(metadata_blocks) if metadata_blocks else "",
                        "commandUuid": entry.get("command_uuid") or "",
                    }
                    table_row = _billing_table_row(entry)
                    if table_row is not None:
                        cmd["tableRow"] = table_row
                    commands.append(cmd)
                section_items.append({
                    "id": parent_id,
                    "display": f"{display_name} ({len(children)})",
                    "children": children,
                })
            else:
                only = entries[0]
                # Prefer the per-entry title for the leaf label so the flat
                # (note-order) list reads "Display Name: <actual title>"
                # rather than "Display Name: Display Name" when there's only
                # one entry. Fall back to display_name for entries whose
                # title extractor returns nothing.
                leaf_label = (only.get("title") or "").strip() or display_name
                # Same idea for the section-view sidebar row: when the entry
                # has a meaningful per-row title (e.g., a customCommand
                # whose schema_key humanizes to "Observation Summary"), use
                # "Display Name: <title>" so the row carries the actual
                # subject instead of just "Custom Command".
                only_title = (only.get("title") or "").strip()
                if only_title and only_title != display_name:
                    sidebar_display = f"{display_name}: {only_title}"
                else:
                    sidebar_display = display_name
                section_items.append({
                    "id": parent_id,
                    "display": sidebar_display,
                    "children": [],
                })
                metadata_blocks = only.get("metadata_blocks") or []
                cmd = {
                    "id": parent_id,
                    "section": section["key"],
                    "displayText": display_name,
                    "label": leaf_label,
                    "printHtml": render_blocks(only["blocks"]),
                    "metadataHtml": render_blocks(metadata_blocks) if metadata_blocks else "",
                    "commandUuid": only.get("command_uuid") or "",
                }
                table_row = _billing_table_row(only)
                if table_row is not None:
                    cmd["tableRow"] = table_row
                commands.append(cmd)

        section_data = {
            "key": section["key"],
            "title": section["title"],
            "items": section_items,
        }
        if section["key"] == PINNED_SECTION_KEY:
            pinned_section = section_data
        else:
            sections.append(section_data)

    # If we built a billing block, append a "Related Diagnosis Codes" row
    # listing every billable diagnosis on the note (mimicking the note footer
    # in home-app). This covers diagnoses that aren't linked to a specific
    # CPT line item via Assessments.
    note_diagnoses = template_context.get("note_diagnoses") or []
    if pinned_section and note_diagnoses:
        cmd_id += 1
        diagnoses_id = f"cmd-{cmd_id}"
        diagnosis_blocks: list[dict] = [
            {"kind": "heading_plain", "value": "Related Diagnosis Codes"},
        ]
        for d in note_diagnoses:
            code = (d.get("code") or "").strip()
            display = (d.get("display") or "").strip()
            if not code and not display:
                continue
            if code and display:
                value = f"{code} — {display}"
            else:
                value = code or display
            diagnosis_blocks.append({"kind": "body", "value": value})
        pinned_section["items"].append({
            "id": diagnoses_id,
            "display": "Related Diagnosis Codes",
            "children": [],
        })
        commands.append({
            "id": diagnoses_id,
            "section": PINNED_SECTION_KEY,
            "displayText": "Related Diagnosis Codes",
            "label": "Related Diagnosis Codes",
            "printHtml": render_blocks(diagnosis_blocks),
            "commandUuid": "",
        })

    # Build one item per follow-up command (a note may have multiple).
    follow_ups = template_context.get("follow_ups") or []
    # Fallback for older extractor shape: synthesize one from the singular fields.
    if not follow_ups and template_context.get("follow_up_date"):
        follow_ups = [{
            "date": template_context.get("follow_up_date", ""),
            "rfv": template_context.get("follow_up_rfv", ""),
            "note_type": template_context.get("follow_up_note_type", ""),
        }]

    if follow_ups:
        plan_section = next((s for s in sections if s["key"] == "plan"), None)
        if plan_section is None:
            plan_section = {"key": "plan", "title": "Plan", "items": []}
            sections.append(plan_section)

        parent_cmd_id = cmd_id + 1
        cmd_id = parent_cmd_id
        parent_id = f"cmd-{parent_cmd_id}"

        def _follow_up_blocks(fu: dict) -> list[dict]:
            fu_blocks = [{"kind": "heading", "prefix": "Follow Up", "value": str(fu.get("date") or "")}]
            if fu.get("note_type"):
                fu_blocks.append({"kind": "field", "label": "VISIT TYPE", "value": fu["note_type"]})
            if fu.get("rfv"):
                fu_blocks.append({"kind": "field", "label": "REASON FOR VISIT", "value": fu["rfv"]})
            if fu.get("comment"):
                fu_blocks.append({"kind": "field", "label": "SCHEDULING COMMENTS", "value": fu["comment"]})
            return fu_blocks

        if len(follow_ups) == 1:
            fu = follow_ups[0]
            plan_section["items"].append({"id": parent_id, "display": "Follow Up", "children": []})
            commands.append({
                "id": parent_id,
                "section": "plan",
                "displayText": "Follow Up",
                "label": "Follow Up",
                "printHtml": render_blocks(_follow_up_blocks(fu)),
                "commandUuid": fu.get("_command_uuid") or "",
            })
        else:
            children = []
            for fu in follow_ups:
                cmd_id += 1
                child_id = f"cmd-{cmd_id}"
                child_title = (fu.get("date") or fu.get("rfv") or "Follow Up")[:60]
                children.append({"id": child_id, "display": child_title})
                commands.append({
                    "id": child_id,
                    "section": "plan",
                    "displayText": "Follow Up",
                    "label": child_title,
                    "printHtml": render_blocks(_follow_up_blocks(fu)),
                    "commandUuid": fu.get("_command_uuid") or "",
                })
            plan_section["items"].append({
                "id": parent_id,
                "display": f"Follow Up ({len(children)})",
                "children": children,
            })

    section_titles = {s["key"]: s["title"] for s in sections}
    if pinned_section:
        section_titles[pinned_section["key"]] = pinned_section["title"]
    note_data = {
        "header": header,
        "commands": commands,
        "sectionTitles": section_titles,
        # Ordered command UUIDs from the note body; the modal's "note order" mode
        # sorts the flat command list by this, appending non-body items at the end.
        "bodyOrder": template_context.get("note_body_order") or [],
        # Section keys that the JS keeps out of the flat list and always renders
        # in their own block (preview + print). Section view already shows them
        # in their own server-rendered block too.
        "pinnedSections": [PINNED_SECTION_KEY] if pinned_section else [],
        # SIGNATURES footer lines (signed-by / amendment / currently-unsigned).
        # Always rendered at the end of the print preview, not selectable.
        "signatureLines": template_context.get("signature_lines") or [],
    }

    note = template_context.get("note")
    return {
        "appointment_date": template_context.get("appointment_date", ""),
        "sections": sections,
        "pinned_section": pinned_section,
        "note_data_json": json.dumps(note_data, default=str),
        "note_dbid": note.dbid if note else "",
        # External UUID — this is what the JS sends as note_id to the API, which
        # resolves notes by Note.id (not the enumerable dbid).
        "note_uuid": str(note.id) if note else "",
    }


class CustomizePrintAPI(SimpleAPI):
    """SimpleAPI that renders the Customize & Print modal HTML."""

    PREFIX = "/customize"

    def authenticate(self, credentials: Credentials) -> bool:
        try:
            logged_in_user = SessionCredentials(self.request).logged_in_user
            if logged_in_user["type"] == "Staff":
                return True
        except InvalidCredentialsError:
            pass

        api_key_secret = self.secrets.get("simple-api-key")
        request_auth_key = self.request.headers.get("Authorization")
        if api_key_secret and request_auth_key and compare_digest(
            api_key_secret.encode(), request_auth_key.encode()
        ):
            return True
        return False

    def _get_or_create_preference(
        self, note_id: str | int
    ) -> CustomizedNotePrint | None:
        """Return the latest DRAFT preference for this note, or create a fresh draft.

        `note_id` is the Note's external UUID (`Note.id`), not the internal dbid.
        """
        note = Note.objects.filter(id=note_id).first()
        if not note:
            return None
        pref = (
            CustomizedNotePrint.objects
            .filter(note=note, status=CustomizedNotePrint.STATUS_DRAFT)
            .order_by("-updated_at")
            .first()
        )
        if pref is None:
            pref = CustomizedNotePrint.objects.create(
                note=note, status=CustomizedNotePrint.STATUS_DRAFT,
            )
        return pref

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        note_id = self.request.query_params.get("note_id")
        log.info(f"Customize & Print for patient {patient_id}, note {note_id}")

        extractor = NoteDataExtractor(patient_id=patient_id, note_id=note_id)
        template_context = extractor.get_template_context()
        customize_context = build_customize_print_context(template_context)
        customize_context["cache_bust"] = _CACHE_BUST

        return [
            HTMLResponse(
                render_to_string("templates/customize_print.html", context=customize_context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/state")
    def get_state(self) -> list[Response | Effect]:
        note_id = self.request.query_params.get("note_id")
        if not note_id:
            return [JSONResponse({"error": "note_id required"}, status_code=HTTPStatus.BAD_REQUEST)]

        pref = self._get_or_create_preference(note_id)
        if not pref:
            return [JSONResponse({"error": "note not found"}, status_code=HTTPStatus.NOT_FOUND)]

        return [JSONResponse({
            "header_text": pref.header_text or "",
            "footer_text": pref.footer_text or "",
            "selection": pref.selection or {},
            "status": pref.status or CustomizedNotePrint.STATUS_DRAFT,
            "updated_at": pref.updated_at.isoformat() if pref.updated_at else None,
        }, status_code=HTTPStatus.OK)]

    @api.post("/state")
    def save_state(self) -> list[Response | Effect]:
        try:
            body = self.request.json()
        except (ValueError, TypeError):
            return [JSONResponse({"error": "invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        note_id = body.get("note_id") if isinstance(body, dict) else None
        if not note_id:
            return [JSONResponse({"error": "note_id required"}, status_code=HTTPStatus.BAD_REQUEST)]

        pref = self._get_or_create_preference(note_id)
        if not pref:
            return [JSONResponse({"error": "note not found"}, status_code=HTTPStatus.NOT_FOUND)]

        if "header_text" in body:
            pref.header_text = str(body.get("header_text") or "")
        if "footer_text" in body:
            pref.footer_text = str(body.get("footer_text") or "")
        if "selection" in body and isinstance(body["selection"], dict):
            pref.selection = body["selection"]
        if "status" in body:
            incoming_status = str(body.get("status") or "").strip()
            if incoming_status in (
                CustomizedNotePrint.STATUS_DRAFT,
                CustomizedNotePrint.STATUS_FINAL,
            ):
                pref.status = incoming_status
        pref.save()

        return [JSONResponse({
            "status": pref.status,
            "updated_at": pref.updated_at.isoformat() if pref.updated_at else None,
        }, status_code=HTTPStatus.OK)]

    @api.get("/finals")
    def list_finals(self) -> list[Response | Effect]:
        """Return finalized prints for the note with fresh presigned PDF URLs."""
        note_id = self.request.query_params.get("note_id")
        if not note_id:
            return [JSONResponse({"error": "note_id required"}, status_code=HTTPStatus.BAD_REQUEST)]

        note = Note.objects.filter(id=note_id).first()
        if not note:
            return [JSONResponse({"error": "note not found"}, status_code=HTTPStatus.NOT_FOUND)]

        # Defer the multi-MB text columns so listing finals stays cheap.
        rows = (
            CustomizedNotePrint.objects
            .filter(note=note, status=CustomizedNotePrint.STATUS_FINAL)
            .order_by("-pdf_generated_at")
            .select_related("document_reference")
            .defer("pdf_base64", "html_content")
        )

        finals = []
        for row in rows:
            # Legacy rows pre-date the `uuid` default and have ``None`` here,
            # which serialized as the string ``"None"`` in the response and
            # broke the DELETE endpoint. Lazily backfill a fresh UUID on read
            # so the row becomes addressable.
            if not row.uuid:
                from uuid import uuid4
                row.uuid = str(uuid4())
                row.save(update_fields=("uuid",))
            doc_ref_fhir_id = ""
            doc_ref = row.document_reference
            description = row.description or ""
            if doc_ref is not None:
                doc_ref_fhir_id = str(doc_ref.id) if getattr(doc_ref, "id", None) else ""
                if not description:
                    description = (
                        getattr(doc_ref, "related_object_document_title", "")
                        or getattr(doc_ref, "document", "")
                        or ""
                    )
            # Comment is stored locally so we can show it in the Previous
            # Versions overlay without making a FHIR round-trip per row.
            comment = row.comment or ""
            if not comment and doc_ref is not None:
                # Fall back to whatever the DocumentReference proxy exposes
                # as the related-object-comment, for rows created before the
                # local `comment` column was added.
                comment = (
                    getattr(doc_ref, "related_object_document_comment", "") or ""
                )
            # Always link to the local PDF endpoint, addressed by the row's
            # non-enumerable UUID (never the sequential dbid). It returns 404 for
            # the rare row with no stored base64 (`serve_final_pdf`).
            local_pdf_url = f"/plugin-io/api/patient_visit_summary/customize/finals/{row.uuid}/pdf"
            finals.append({
                "id": str(row.uuid),
                "description": description,
                "comment": comment,
                "generated_at": row.pdf_generated_at.isoformat() if row.pdf_generated_at else None,
                "document_reference_id": doc_ref_fhir_id,
                "pdf_url": local_pdf_url,
            })
        return [JSONResponse({"finals": finals}, status_code=HTTPStatus.OK)]

    @api.get("/finals/<final_uuid>/pdf")
    def serve_final_pdf(self) -> list[Response | Effect]:
        """Serve the stored PDF bytes for a finalized print, addressed by UUID."""
        final_uuid = self.request.path_params.get("final_uuid")
        if not final_uuid:
            return [Response(b"", status_code=HTTPStatus.BAD_REQUEST, content_type="text/plain")]
        try:
            # Validate the shape, then match the canonical string stored in the
            # TextField `uuid` column.
            parsed_uuid = str(UUID(str(final_uuid)))
        except (TypeError, ValueError):
            return [Response(b"", status_code=HTTPStatus.BAD_REQUEST, content_type="text/plain")]
        row = CustomizedNotePrint.objects.filter(uuid=parsed_uuid).only("pdf_base64").first()
        if row is None or not row.pdf_base64:
            return [Response(b"", status_code=HTTPStatus.NOT_FOUND, content_type="text/plain")]
        try:
            pdf_bytes = base64.b64decode(row.pdf_base64)
        except (ValueError, TypeError):
            return [Response(b"", status_code=HTTPStatus.INTERNAL_SERVER_ERROR, content_type="text/plain")]
        return [Response(pdf_bytes, status_code=HTTPStatus.OK, content_type="application/pdf")]

    @api.delete("/finals/<final_uuid>")
    def delete_final(self) -> list[Response | Effect]:
        """Delete the local CustomizedNotePrint row for a saved version.

        Only the plugin's custom-data record is removed. The FHIR
        DocumentReference attached to the patient's chart is **not** touched —
        the saved PDF remains accessible through the patient's documents list
        and via the FHIR API, just no longer surfaced in this modal's
        Previous Versions overlay.
        """
        final_uuid = self.request.path_params.get("final_uuid")
        if not final_uuid:
            return [JSONResponse({"error": "final_uuid required"}, status_code=HTTPStatus.BAD_REQUEST)]
        try:
            parsed_uuid = str(UUID(str(final_uuid)))
        except (TypeError, ValueError):
            return [JSONResponse({"error": "invalid uuid"}, status_code=HTTPStatus.BAD_REQUEST)]
        row = CustomizedNotePrint.objects.filter(uuid=parsed_uuid).first()
        if row is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        dbid = row.dbid
        doc_ref_dbid = getattr(row, "document_reference_id", None)
        row.delete()
        log.info(
            f"CustomizedNotePrint deleted: dbid={dbid} uuid={parsed_uuid} "
            f"document_reference_id={doc_ref_dbid} (DocumentReference retained)"
        )
        return [JSONResponse({"deleted": True}, status_code=HTTPStatus.OK)]

    @api.post("/print_pdf")
    def print_pdf(self) -> list[Response | Effect]:
        """Render a PDF from the preview HTML, attach it to the patient as a
        FHIR DocumentReference, and record both references on the note print row."""
        try:
            body = self.request.json()
        except (ValueError, TypeError):
            return [JSONResponse({"error": "invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        note_id = body.get("note_id") if isinstance(body, dict) else None
        html = body.get("html") if isinstance(body, dict) else None
        description = (body.get("description") if isinstance(body, dict) else "") or ""
        description = str(description).strip() or "Customized Note Printout"
        # Internal note saved on the DocumentReference via the Canvas FHIR
        # `document-reference-comment` extension. Surfaces in the chart's
        # document detail view; never printed in the PDF body.
        comment = (body.get("comment") if isinstance(body, dict) else "") or ""
        comment = str(comment).strip()
        if not note_id or not html:
            return [JSONResponse({"error": "note_id and html required"}, status_code=HTTPStatus.BAD_REQUEST)]

        note = Note.objects.filter(id=note_id).select_related("patient").first()
        if not note:
            return [JSONResponse({"error": "note not found"}, status_code=HTTPStatus.NOT_FOUND)]
        patient_fhir_id = str(note.patient.id) if note.patient else None
        if not patient_fhir_id:
            return [JSONResponse({"error": "patient not found on note"}, status_code=HTTPStatus.NOT_FOUND)]

        # 1. Generate PDF (returns a presigned S3 URL).
        pdf_result = pdf_generator.from_html(html)
        if pdf_result is None or not pdf_result.url:
            log.error("PDF generation failed: no URL returned")
            return [JSONResponse({"error": "pdf generation failed"}, status_code=HTTPStatus.BAD_GATEWAY)]
        pdf_url = pdf_result.url

        # 2. Download the PDF so we can embed it in the DocumentReference.
        #    Use the SDK HTTP client (enforced timeout, URL validation, metrics).
        try:
            pdf_resp = Http().get(pdf_url)
            pdf_resp.raise_for_status()
            pdf_bytes = pdf_resp.content
        except RequestException as exc:
            log.error(f"PDF download failed: {exc}")
            return [JSONResponse({"error": "pdf download failed"}, status_code=HTTPStatus.BAD_GATEWAY)]

        # 3. Create a FHIR DocumentReference attached to the patient.
        reviewer_fhir_id = ""
        if getattr(note, "provider", None) and getattr(note.provider, "id", None):
            reviewer_fhir_id = str(note.provider.id)

        client_id = self.secrets.get("fhir-client-id")
        client_secret = self.secrets.get("fhir-client-secret")
        doc_ref_fhir_id = ""
        doc_ref_sdk = None

        if not (client_id and client_secret):
            log.warning("FHIR DocumentReference skipped: fhir-client-id / fhir-client-secret not configured")
        elif not reviewer_fhir_id:
            log.warning("FHIR DocumentReference skipped: no reviewer (note has no provider)")
        else:
            # Record the create moment so we can look up the row the SDK
            # created when the FHIR response body comes back empty.
            create_started_at = datetime.now(timezone.utc)
            try:
                dos = getattr(note, "datetime_of_service", None)
                clinical_date = (
                    dos.date().isoformat() if dos else datetime.now(timezone.utc).date().isoformat()
                )
                fhir = CanvasFhir(client_id=client_id, client_secret=client_secret)
                extensions = [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-clinical-date",
                        "valueDate": clinical_date,
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-reviewer",
                        "valueReference": {
                            "reference": f"Practitioner/{reviewer_fhir_id}",
                            "type": "Practitioner",
                        },
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-review-mode",
                        "valueCode": "RN",
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-requires-signature",
                        "valueBoolean": False,
                    },
                ]
                if comment:
                    extensions.append({
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-comment",
                        "valueString": comment,
                    })
                doc_ref = fhir.create("DocumentReference", {
                    "resourceType": "DocumentReference",
                    "extension": extensions,
                    "status": "current",
                    "description": description,
                    "type": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "34109-9",
                            "display": "Note",
                        }],
                    },
                    "category": [{
                        "coding": [{
                            "system": "http://schemas.canvasmedical.com/fhir/document-reference-category",
                            "code": "uncategorizedclinicaldocument",
                        }],
                    }],
                    "subject": {
                        "reference": f"Patient/{patient_fhir_id}",
                        "type": "Patient",
                    },
                    "content": [{
                        "attachment": {
                            "contentType": "application/pdf",
                            "data": base64.b64encode(pdf_bytes).decode("ascii"),
                        }
                    }],
                })
                log.info(f"FHIR DocumentReference create returned: {doc_ref!r}")
                doc_ref_fhir_id = str(doc_ref.get("id") or "") if isinstance(doc_ref, dict) else ""
            except Exception as exc:
                # Canvas FHIR often returns 201 Created with an empty body, which
                # makes the SDK's response.json() raise JSONDecodeError even though
                # the resource WAS created. We fall through to the SDK lookup either
                # way; the log level reflects whether this was a real HTTP failure.
                resp = getattr(exc, "response", None)
                if resp is not None:
                    try:
                        body = (resp.text or "")[:2000]
                    except Exception:
                        body = ""
                    log.error(f"FHIR DocumentReference create failed: {exc}; body={body}")
                elif isinstance(exc, json.JSONDecodeError):
                    log.info(f"FHIR DocumentReference create body was empty; resolving via SDK lookup.")
                else:
                    log.warning(f"FHIR DocumentReference create raised unexpectedly: {exc!r}")

            # Resolve the SDK DocumentReference record. Canvas FHIR often returns
            # 201 Created with an empty body, so we can't always rely on the id
            # from the response — fall back to the most recent DocumentReference
            # for this patient created since we started the request.
            if doc_ref_sdk is None:
                recent = (
                    DocumentReference.objects
                    .for_patient(patient_fhir_id)
                    .filter(created__gte=create_started_at)
                    .order_by("-created")
                    .first()
                )
                if recent is None and doc_ref_fhir_id:
                    recent = DocumentReference.objects.filter(id=doc_ref_fhir_id).first()
                if recent is None:
                    # Replication lag or no match: fall back to newest for patient.
                    recent = (
                        DocumentReference.objects
                        .for_patient(patient_fhir_id)
                        .order_by("-created")
                        .first()
                    )
                if recent is not None:
                    doc_ref_sdk = recent
                    doc_ref_fhir_id = str(recent.id)
                    log.info(
                        f"DocumentReference resolved: id={doc_ref_fhir_id} dbid={recent.dbid}"
                    )
                else:
                    log.warning(
                        "Could not resolve newly-created DocumentReference via SDK lookup."
                    )

        # 4. Persist on the note-print row and mark as final. We store the HTML
        # and base64 PDF locally so previous versions can be re-served even when
        # FHIR DocumentReference creation is disabled or fails.
        pref = self._get_or_create_preference(note_id)
        if pref:
            if doc_ref_sdk is not None:
                pref.document_reference = doc_ref_sdk
            pref.description = description
            pref.comment = comment
            pref.html_content = html
            pref.pdf_base64 = base64.b64encode(pdf_bytes).decode("ascii")
            pref.pdf_generated_at = datetime.now(timezone.utc)
            pref.status = CustomizedNotePrint.STATUS_FINAL
            pref.save()
            log.info(
                f"CustomizedNotePrint saved: dbid={pref.dbid} "
                f"document_reference_id={getattr(pref, 'document_reference_id', None)}"
            )

        return [JSONResponse({
            "pdf_url": pdf_url,
            "document_reference_id": doc_ref_fhir_id,
        }, status_code=HTTPStatus.OK)]
