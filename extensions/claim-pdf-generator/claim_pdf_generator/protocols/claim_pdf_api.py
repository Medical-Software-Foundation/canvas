"""SimpleAPI handler for generating superbill and CMS-1500 (HCFA) PDF forms from claim data."""

from datetime import datetime, timezone
from http import HTTPStatus
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils import Http
from canvas_sdk.utils.pdf import pdf_generator
from canvas_sdk.v1.data.claim import Claim
from canvas_sdk.v1.data.organization import Organization
from canvas_sdk.v1.data.posting import BasePosting
from logger import log


def _format_icd10(code: str) -> str:
    """Format an ICD-10 code with a dot after the first 3 characters."""
    if len(code) > 3:
        return f"{code[:3]}.{code[3:]}"
    return code


def _format_phone(phone: str) -> str:
    """Format a 10-digit phone string as (XXX) XXX-XXXX."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return phone


def _render_claim_template(template_name: str, context_data: dict) -> str:
    """Render a template from the templates directory with the provided context."""
    return render_to_string(f"templates/{template_name}", context_data) or ""


def _format_datetime_of_service(dt: datetime | str | None, tz_name: str) -> str:
    """Format a datetime of service with timezone abbreviation."""
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
        if hasattr(dt, "astimezone"):
            local_dt = dt.astimezone(tz)
        else:
            return str(dt)
        abbr = local_dt.strftime("%Z")
        return f"{local_dt.strftime('%Y-%m-%d')} at {local_dt.strftime('%I:%M %p').lstrip('0').lower()} {abbr}"
    except Exception:
        return str(dt)


def _build_claim_context(claim: Claim, tz_name: str = "") -> dict:
    """Build a template context dictionary from a Claim instance."""
    # Patient
    patient = getattr(claim, "patient", None)

    # Provider (OneToOne)
    provider = getattr(claim, "provider", None)

    # Active coverages ordered by payer_order
    primary_coverage = claim.coverages.filter(active=True, payer_order="Primary").first()
    secondary_coverage = claim.coverages.filter(active=True, payer_order="Secondary").first()

    # Line items
    line_items = list(claim.get_active_claim_line_items())

    # Build enriched line item list
    enriched_line_items = []
    for item in line_items:
        # TODO: Update to use ClaimLineItemModifier once available in the SDK.
        # Currently falls back to BillingLineItem.modifiers with dedup.
        modifiers: list[str] = []
        if item.billing_line_item_id:
            modifiers = list(dict.fromkeys(
                item.billing_line_item.modifiers.values_list("code", flat=True)
            ))
        # Get linked diagnosis codes formatted with dots
        linked_diags = list(
            item.diagnosis_codes.filter(linked=True).values_list(
                "claim_diagnosis_code__code", flat=True
            )
        )
        linked_diag_codes = [_format_icd10(c) for c in linked_diags if c]
        enriched_line_items.append(
            {
                "proc_code": item.proc_code,
                "display": item.display,
                "from_date": item.from_date,
                "thru_date": item.thru_date,
                "place_of_service": item.place_of_service or "",
                "units": item.units,
                "charge": item.charge,
                "modifiers": modifiers,
                "linked_diag_codes": linked_diag_codes,
                "narrative": item.narrative,
            }
        )

    # Diagnosis codes ordered by rank (with formatted codes)
    raw_diagnosis_codes = list(claim.diagnosis_codes.order_by("rank"))
    diagnosis_codes = [
        {"rank": dx.rank, "code": _format_icd10(dx.code), "display": dx.display}
        for dx in raw_diagnosis_codes
    ]

    # Postings
    postings = list(claim.postings.filter(entered_in_error__isnull=True))

    # Note / date of service and staff provider (for credentialed name)
    note = claim.note
    note_provider = getattr(note, "provider", None) if note else None
    provider_credentialed_name = ""
    bill_through_org = False
    if note_provider:
        provider_credentialed_name = getattr(note_provider, "credentialed_name", "") or ""
        bill_through_org = getattr(note_provider, "bill_through_organization", False)

    # Format date of service with timezone
    raw_dos = getattr(note, "datetime_of_service", None) if note else None
    formatted_dos = _format_datetime_of_service(raw_dos, tz_name)

    # Tax ID: use org tax_id if provider bills through org, else provider tax_id
    tax_id = ""
    practice_location = getattr(note, "location", None) if note else None
    if bill_through_org and practice_location and practice_location.organization:
        tax_id = getattr(practice_location.organization, "tax_id", "") or ""
    elif note_provider:
        tax_id = getattr(note_provider, "tax_id", "") or ""

    # Practice location phone and fax from telecom
    location_phone = ""
    location_fax = ""
    if practice_location:
        for contact in practice_location.telecom.all():
            log.info(f"[Superbill] telecom: system={contact.system} use={contact.use} value={contact.value}")
            if contact.system == "phone" and not location_phone:
                location_phone = _format_phone(contact.value)
            elif contact.system == "fax" and not location_fax:
                location_fax = _format_phone(contact.value)
        # Fallback to organization phone/fax
        if not location_phone and practice_location.organization:
            org_phone = getattr(practice_location.organization, "main_phone", None)
            if org_phone:
                location_phone = _format_phone(str(org_phone))
        if not location_fax and practice_location.organization:
            org_fax = getattr(practice_location.organization, "fax_number", None)
            if org_fax:
                location_fax = _format_phone(str(org_fax))
    log.info(f"[Superbill] location_phone={location_phone} location_fax={location_fax}")

    # Organization (singleton)
    org = Organization.objects.first()

    # Patient address (ClaimPatient has addr1/addr2/city/state/zip directly)
    patient_address = ""
    if patient:
        parts = []
        addr1 = getattr(patient, "addr1", "") or ""
        addr2 = getattr(patient, "addr2", "") or ""
        city = getattr(patient, "city", "") or ""
        state = getattr(patient, "state", "") or ""
        zip_code = getattr(patient, "zip", "") or ""
        if addr1:
            parts.append(addr1)
        if addr2:
            parts.append(addr2)
        if city or state or zip_code:
            parts.append(f"{city}, {state} {zip_code}".strip())
        patient_address = ", ".join(p for p in parts if p)

    # Format patient phone
    patient_phone = ""
    if patient:
        phone_val = getattr(patient, "phone", None)
        if phone_val:
            patient_phone = _format_phone(str(phone_val))

    return {
        "claim": claim,
        "organization": org,
        "practice_location": practice_location,
        "location_phone": location_phone,
        "location_fax": location_fax,
        "patient": patient,
        "patient_address": patient_address,
        "patient_phone": patient_phone,
        "provider": provider,
        "provider_credentialed_name": provider_credentialed_name,
        "tax_id": tax_id,
        "primary_coverage": primary_coverage,
        "secondary_coverage": secondary_coverage,
        "line_items": enriched_line_items,
        "diagnosis_codes": diagnosis_codes,
        "postings": postings,
        "note": note,
        "formatted_dos": formatted_dos,
        "total_charges": claim.total_charges,
        "total_paid": claim.total_paid,
        "total_adjusted": claim.total_adjusted,
        "balance": claim.balance,
        "format_phone": _format_phone,
    }


class ClaimPdfAPI(APIKeyAuthMixin, SimpleAPI):
    """API endpoints for generating superbill and HCFA (CMS-1500) PDFs from claim data."""

    PREFIX = "/claim-forms"

    @api.get("/superbill/<claim_id>")
    def superbill(self) -> list[Response | Effect]:
        """Generate a superbill PDF for the given claim."""
        claim_id: str = self.request.path_params["claim_id"]
        return self._generate_pdf(claim_id, form_type="superbill", template="superbill.html")

    @api.get("/hcfa/<claim_id>")
    def hcfa(self) -> list[Response | Effect]:
        """Generate a CMS-1500 (HCFA) PDF for the given claim."""
        claim_id: str = self.request.path_params["claim_id"]
        return self._generate_pdf(claim_id, form_type="hcfa", template="hcfa.html")

    def _generate_pdf(
        self, claim_id: str, form_type: str, template: str
    ) -> list[Response | Effect]:
        """Core logic: fetch claim, render HTML, generate PDF, return response."""
        claim = Claim.objects.filter(id=claim_id).first()
        if not claim:
            log.warning(f"[ClaimPdfAPI] Claim not found: {claim_id}")
            return [
                JSONResponse({"error": "Claim not found"}, status_code=HTTPStatus.NOT_FOUND)
            ]

        tz_name = self.secrets.get("timezone", "")
        context = _build_claim_context(claim, tz_name=tz_name)
        html = _render_claim_template(template, context)

        pdf_response = pdf_generator.from_html(content=html)
        if not pdf_response or not pdf_response.url:
            log.error(f"[ClaimPdfAPI] PDF generation failed for claim {claim_id}")
            return [
                JSONResponse(
                    {"error": "PDF generation failed"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        fmt = self.request.query_params.get("format", "url")
        if fmt == "pdf":
            http = Http()
            raw_pdf = http.get(pdf_response.url)
            return [
                Response(
                    content=raw_pdf.content,
                    status_code=HTTPStatus.OK,
                    headers={"Content-Type": "application/pdf"},
                )
            ]

        return [
            JSONResponse(
                {
                    "pdf_url": pdf_response.url,
                    "claim_id": claim_id,
                    "form_type": form_type,
                }
            )
        ]
