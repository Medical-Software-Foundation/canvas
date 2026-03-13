"""ActionButton handlers that add superbill and HCFA PDF buttons to note headers."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.utils.pdf import pdf_generator
from canvas_sdk.v1.data.claim import Claim
from logger import log

from claim_pdf_generator.protocols.claim_pdf_api import (
    _build_claim_context,
    _load_template,
    _render_template,
)

_MODAL_STYLE = """
<style>
  body { font-family: Arial, Helvetica, sans-serif; font-size: 13px; color: #222; margin: 0; padding: 20px; }
  h2 { margin: 0 0 12px; font-size: 15px; }
  a.pdf-link {
    display: inline-block; margin-top: 8px; padding: 10px 18px;
    background: #1a56db; color: #fff; text-decoration: none;
    border-radius: 4px; font-weight: bold; font-size: 13px;
  }
  a.pdf-link:hover { background: #1e40af; }
  .error { color: #b91c1c; font-weight: bold; }
  .meta { color: #555; font-size: 11px; margin-top: 10px; }
</style>
"""


def _generate_pdf_modal_html(claim_id: str, form_type: str, template: str) -> str:
    """Generate HTML for the PDF link modal. Returns error HTML if generation fails."""
    claim = Claim.objects.filter(id=claim_id).first()
    if not claim:
        return f"{_MODAL_STYLE}<p class='error'>Claim not found (ID: {claim_id})</p>"

    ctx = _build_claim_context(claim)
    template_str = _load_template(template)
    html = _render_template(template_str, ctx)

    pdf_response = pdf_generator.from_html(content=html)
    if not pdf_response or not pdf_response.url:
        log.error(f"[NoteActionButton] PDF generation failed for claim {claim_id}")
        return f"{_MODAL_STYLE}<p class='error'>PDF generation failed. Please try again.</p>"

    label = "Superbill" if form_type == "superbill" else "CMS-1500 (HCFA)"
    patient = getattr(claim, "patient", None)
    patient_name = ""
    if patient:
        patient_name = f"{patient.last_name}, {patient.first_name}"

    return (
        f"{_MODAL_STYLE}"
        f"<h2>{label} Ready</h2>"
        f"{'<p class=meta>Patient: ' + patient_name + '</p>' if patient_name else ''}"
        f"<p class='meta'>Claim ID: {claim_id}</p>"
        f"<a class='pdf-link' href='{pdf_response.url}' target='_blank'>"
        f"Open {label} PDF</a>"
        f"<p class='meta' style='margin-top:16px;'>Link expires after a short time. "
        f"Click to open or right-click to download.</p>"
    )


def _get_claim_for_note(note_id: str) -> Claim | None:
    """Return the first active Claim linked to the given note, or None."""
    return Claim.objects.active().filter(note__id=note_id).first()


class SuperbillButton(ActionButton):
    """Note header button that generates and opens a superbill PDF for the note's claim."""

    BUTTON_TITLE = "Superbill"
    BUTTON_KEY = "GENERATE_SUPERBILL"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER
    PRIORITY = 10

    def visible(self) -> bool:
        """Show the button only if the note has an associated claim."""
        note_id = self.event.context.get("note_id")
        if not note_id:
            return False
        return bool(Claim.objects.active().filter(note__id=note_id).exists())

    def handle(self) -> list[Effect]:
        """Generate a superbill PDF and present a link in a modal."""
        note_id = self.event.context.get("note_id", "")
        claim = _get_claim_for_note(note_id)
        if not claim:
            log.warning(f"[SuperbillButton] No claim found for note {note_id}")
            content = f"{_MODAL_STYLE}<p class='error'>No claim found for this note.</p>"
        else:
            content = _generate_pdf_modal_html(
                claim_id=str(claim.id),
                form_type="superbill",
                template="superbill.html",
            )

        return [
            LaunchModalEffect(
                content=content,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Superbill",
            ).apply()
        ]


class HcfaButton(ActionButton):
    """Note header button that generates and opens a CMS-1500 (HCFA) PDF for the note's claim."""

    BUTTON_TITLE = "CMS-1500"
    BUTTON_KEY = "GENERATE_HCFA"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER
    PRIORITY = 11

    def visible(self) -> bool:
        """Show the button only if the note has an associated claim."""
        note_id = self.event.context.get("note_id")
        if not note_id:
            return False
        return bool(Claim.objects.active().filter(note__id=note_id).exists())

    def handle(self) -> list[Effect]:
        """Generate a CMS-1500 PDF and present a link in a modal."""
        note_id = self.event.context.get("note_id", "")
        claim = _get_claim_for_note(note_id)
        if not claim:
            log.warning(f"[HcfaButton] No claim found for note {note_id}")
            content = f"{_MODAL_STYLE}<p class='error'>No claim found for this note.</p>"
        else:
            content = _generate_pdf_modal_html(
                claim_id=str(claim.id),
                form_type="hcfa",
                template="hcfa.html",
            )

        return [
            LaunchModalEffect(
                content=content,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="CMS-1500 (HCFA)",
            ).apply()
        ]
