"""SimpleAPI handler for generating superbill and CMS-1500 (HCFA) PDF forms from claim data."""

from http import HTTPStatus
from pathlib import Path

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPI, api
from canvas_sdk.utils import Http
from canvas_sdk.utils.pdf import pdf_generator
from canvas_sdk.v1.data.claim import Claim
from django.template import Context, Engine
from logger import log

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _load_template(name: str) -> str:
    """Load an HTML template file from the templates directory."""
    return (TEMPLATES_DIR / name).read_text()


def _render_template(template_str: str, context_data: dict) -> str:
    """Render a Django template string with the provided context."""
    engine = Engine()
    template = engine.from_string(template_str)
    return template.render(Context(context_data))


def _build_claim_context(claim: Claim) -> dict:
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
        modifiers: list[str] = []
        if item.billing_line_item_id:
            modifiers = list(
                item.billing_line_item.modifiers.values_list("code", flat=True)
            )
        diag_pointers = list(
            item.diagnosis_codes.filter(linked=True).values_list(
                "claim_diagnosis_code__rank", flat=True
            )
        )
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
                "diag_pointers": diag_pointers,
                "ndc_code": item.ndc_code,
                "ndc_dosage": item.ndc_dosage,
                "ndc_measure": item.ndc_measure,
                "narrative": item.narrative,
            }
        )

    # Diagnosis codes ordered by rank
    diagnosis_codes = list(claim.diagnosis_codes.order_by("rank"))

    # Note / date of service
    note = claim.note

    return {
        "claim": claim,
        "patient": patient,
        "provider": provider,
        "primary_coverage": primary_coverage,
        "secondary_coverage": secondary_coverage,
        "line_items": enriched_line_items,
        "diagnosis_codes": diagnosis_codes,
        "note": note,
        "total_charges": claim.total_charges,
        "total_paid": claim.total_paid,
        "balance": claim.balance,
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

        context = _build_claim_context(claim)
        template_str = _load_template(template)
        html = _render_template(template_str, context)

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
