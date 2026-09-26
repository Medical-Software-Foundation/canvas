"""SimpleAPI - Summary generation endpoints for visit-summaries."""
from __future__ import annotations

from http import HTTPStatus

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient
from logger import log

from visit_summaries.helpers.llm_service import (
    generate_avs,
    generate_previous_visit_summary,
    generate_since_last_visit_summary,
    render_missing_config_html,
    validate_llm_secrets,
)
from visit_summaries.helpers.note_queries import (
    build_interim_context_for_llm,
    build_note_context_for_llm,
    extract_assess_plan_from_commands,
    extract_chief_complaint,
    extract_medications_from_commands,
    extract_vitals_from_commands,
    format_service_date,
    get_commands_for_note,
    get_most_recent_locked_note,
)
from visit_summaries.helpers.styles import SHARED_CSS


class SummaryApi(StaffSessionAuthMixin, SimpleAPI):
    """Authenticated endpoints that serve loading pages with spinners."""

    PREFIX = "/summary"

    @api.get("/previous-visit")
    def previous_visit_loading(self) -> list[Response | Effect]:
        """Open the panel immediately with a loading spinner."""
        note_id = self.request.query_params.get("note_id", "")
        patient_id = self.request.query_params.get("patient_id", "")
        generate_url = (
            f"/plugin-io/api/visit_summaries/summary-gen/previous-visit"
            f"?note_id={note_id}&patient_id={patient_id}"
        )
        content = render_to_string(
            "templates/summary_loading.html",
            {
                "loading_message": "Generating summary of last visit",
                "generate_url": generate_url,
                "shared_css": SHARED_CSS,
                "hide_header_until_loaded": True,
            },
        )
        return [HTMLResponse(content, status_code=HTTPStatus.OK)]

    @api.get("/since-last-visit")
    def since_last_visit_loading(self) -> list[Response | Effect]:
        """Open the panel immediately with a loading spinner."""
        note_id = self.request.query_params.get("note_id", "")
        patient_id = self.request.query_params.get("patient_id", "")
        generate_url = (
            f"/plugin-io/api/visit_summaries/summary-gen/since-last-visit"
            f"?note_id={note_id}&patient_id={patient_id}"
        )
        content = render_to_string(
            "templates/summary_loading.html",
            {
                "loading_message": "Summarizing activity since last visit",
                "generate_url": generate_url,
                "shared_css": SHARED_CSS,
                "hide_header_until_loaded": True,
            },
        )
        return [HTMLResponse(content, status_code=HTTPStatus.OK)]

    @api.get("/avs")
    def avs_loading(self) -> list[Response | Effect]:
        """Open the panel immediately with a loading spinner."""
        note_id = self.request.query_params.get("note_id", "")
        patient_id = self.request.query_params.get("patient_id", "")
        generate_url = (
            f"/plugin-io/api/visit_summaries/summary-gen/avs"
            f"?note_id={note_id}&patient_id={patient_id}"
        )
        content = render_to_string(
            "templates/summary_loading.html",
            {
                "page_title": "After Visit Summary",
                "loading_message": "Creating your patient's After Visit Summary",
                "generate_url": generate_url,
                "shared_css": SHARED_CSS,
                "show_print_button": True,
                "sticky_header": True,
            },
        )
        return [HTMLResponse(content, status_code=HTTPStatus.OK)]


class SummaryGenerateApi(StaffSessionAuthMixin, SimpleAPI):
    """Generate endpoints called by JS from within authenticated loading pages."""

    PREFIX = "/summary-gen"

    @api.get("/previous-visit")
    def generate_previous_visit(self) -> list[Response | Effect]:
        """Fetch note data, call LLM, return summary HTML as JSON."""
        patient_id = self.request.query_params.get("patient_id", "")
        note_id = self.request.query_params.get("note_id", "")

        missing = validate_llm_secrets(self.secrets)
        if missing:
            return [JSONResponse({"html": render_missing_config_html(missing)}, status_code=HTTPStatus.OK)]

        prior_note = get_most_recent_locked_note(patient_id, exclude_note_id=note_id or None)
        if not prior_note:
            return [JSONResponse({"html": "<p class='no-data'>No prior locked notes found.</p>"}, status_code=HTTPStatus.OK)]

        note_date = format_service_date(prior_note.datetime_of_service, "MMM D, YYYY")

        commands = get_commands_for_note(prior_note)
        chief_complaint = extract_chief_complaint(commands)
        diagnoses, plan_items = extract_assess_plan_from_commands(commands)
        medications = extract_medications_from_commands(commands)
        vitals = extract_vitals_from_commands(commands)

        note_context = build_note_context_for_llm(prior_note)
        summary_html = generate_previous_visit_summary(
            note_context,
            self.secrets,
            chief_complaint=chief_complaint,
            diagnoses=diagnoses,
            medications=medications,
            plan_items=plan_items,
            vitals=vitals,
        )

        return [JSONResponse({"html": summary_html, "note_date": note_date}, status_code=HTTPStatus.OK)]

    @api.get("/since-last-visit")
    def generate_since_last_visit(self) -> list[Response | Effect]:
        """Fetch interim data, call LLM, return summary HTML as JSON."""
        patient_id = self.request.query_params.get("patient_id", "")
        note_id = self.request.query_params.get("note_id", "")

        missing = validate_llm_secrets(self.secrets)
        if missing:
            return [JSONResponse({"html": render_missing_config_html(missing)}, status_code=HTTPStatus.OK)]

        prior_note = get_most_recent_locked_note(patient_id, exclude_note_id=note_id or None)
        if not prior_note:
            return [JSONResponse({"html": "<p class='no-data'>No prior locked notes found.</p>"}, status_code=HTTPStatus.OK)]

        since_date = arrow.get(prior_note.datetime_of_service)
        current_note = Note.objects.filter(dbid=note_id).first() if note_id else None
        if current_note and current_note.datetime_of_service:
            until_date = arrow.get(current_note.datetime_of_service)
        else:
            until_date = arrow.now()

        interim_context = build_interim_context_for_llm(patient_id, since_date, until_date)
        summary_html = generate_since_last_visit_summary(interim_context, self.secrets)

        since_str = format_service_date(since_date, "MMM D, YYYY")
        until_str = format_service_date(until_date, "MMM D, YYYY")
        days = (until_date - since_date).days
        if days == 0:
            day_label = "same day"
        elif days == 1:
            day_label = "1 day"
        else:
            day_label = f"{days} days"
        date_range = f"{since_str} — {until_str} ({day_label})"

        return [JSONResponse({"html": summary_html, "date_range": date_range}, status_code=HTTPStatus.OK)]

    @api.get("/avs")
    def generate_avs_endpoint(self) -> list[Response | Effect]:
        """Fetch note data, call LLM, return AVS HTML as JSON."""
        patient_id = self.request.query_params.get("patient_id", "")
        note_id = self.request.query_params.get("note_id", "")

        missing = validate_llm_secrets(self.secrets)
        if missing:
            return [JSONResponse({"html": render_missing_config_html(missing)}, status_code=HTTPStatus.OK)]

        if not note_id:
            return [JSONResponse({"html": "<p class='error'>Could not load note data.</p>"}, status_code=HTTPStatus.OK)]

        note = Note.objects.select_related("provider").filter(dbid=note_id).first()
        if not note:
            return [JSONResponse({"html": "<p class='error'>Could not load note data.</p>"}, status_code=HTTPStatus.OK)]

        patient = Patient.objects.filter(id=patient_id).first()
        patient_info: dict = {}
        if patient:
            patient_info["first_name"] = patient.first_name or "Patient"
            patient_info["last_name"] = patient.last_name or ""
        if note.datetime_of_service:
            patient_info["visit_date"] = format_service_date(note.datetime_of_service)
        if note.provider:
            first = note.provider.first_name or ""
            last = note.provider.last_name or ""
            provider_name = f"{first} {last}".strip()
            if provider_name:
                patient_info["provider_name"] = provider_name

        commands = get_commands_for_note(note)
        if not commands:
            empty_html = (
                '<div class="banner banner-info">'
                "<p>No commands have been documented in this note yet.</p>"
                "<p>Add commands to the note, then click Generate AVS again.</p>"
                "</div>"
            )
            patient_name = f"{patient_info.get('first_name', '')} {patient_info.get('last_name', '')}".strip()
            visit_date = format_service_date(note.datetime_of_service, "MMM D, YYYY")
            avs_subtitle = ""
            if patient_name and visit_date:
                avs_subtitle = f"for {patient_name} on {visit_date}"
            elif patient_name:
                avs_subtitle = f"for {patient_name}"
            elif visit_date:
                avs_subtitle = f"on {visit_date}"
            return [JSONResponse({"html": empty_html, "avs_subtitle": avs_subtitle}, status_code=HTTPStatus.OK)]

        medications = extract_medications_from_commands(commands)
        _, plan_items = extract_assess_plan_from_commands(commands)

        note_context = build_note_context_for_llm(note)
        avs_html = generate_avs(
            note_context,
            patient_info,
            self.secrets,
            medications=medications,
            plan_items=plan_items,
        )

        patient_name = f"{patient_info.get('first_name', '')} {patient_info.get('last_name', '')}".strip()
        visit_date = format_service_date(note.datetime_of_service, "MMM D, YYYY")
        avs_subtitle = ""
        if patient_name and visit_date:
            avs_subtitle = f"for {patient_name} on {visit_date}"
        elif patient_name:
            avs_subtitle = f"for {patient_name}"
        elif visit_date:
            avs_subtitle = f"on {visit_date}"

        return [JSONResponse({"html": avs_html, "avs_subtitle": avs_subtitle}, status_code=HTTPStatus.OK)]
