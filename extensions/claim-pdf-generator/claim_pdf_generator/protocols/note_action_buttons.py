"""ActionButton handlers that add superbill and HCFA PDF buttons to note headers."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.utils.pdf import pdf_generator
from canvas_sdk.v1.data.claim import Claim
from logger import log

from claim_pdf_generator.protocols.claim_pdf_api import (
    _build_claim_context,
    _render_claim_template,
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


def _generate_pdf_modal_html(claim_id: str, form_type: str, template: str, tz_name: str = "") -> str:
    """Generate HTML for the PDF link modal. Returns error HTML if generation fails."""
    claim = Claim.objects.filter(id=claim_id).first()
    if not claim:
        return f"{_MODAL_STYLE}<p class='error'>Claim not found (ID: {claim_id})</p>"

    ctx = _build_claim_context(claim, tz_name=tz_name)
    html = _render_claim_template(template, ctx)

    log.info(f"[NoteActionButton] Rendered HTML length={len(html) if html else 0} for claim {claim_id}")
    try:
        pdf_response = pdf_generator.from_html(content=html)
    except Exception as exc:
        log.error(f"[NoteActionButton] pdf_generator.from_html raised {type(exc).__name__}: {exc}")
        return f"{_MODAL_STYLE}<p class='error'>PDF generation error: {type(exc).__name__}</p>"
    log.info(f"[NoteActionButton] pdf_response={pdf_response!r} url={getattr(pdf_response, 'url', None)}")
    if not pdf_response or not pdf_response.url:
        log.error(f"[NoteActionButton] PDF generation failed for claim {claim_id}")
        return f"{_MODAL_STYLE}<p class='error'>PDF generation failed. Please try again.</p>"

    return (
        '<style>'
        '  body { margin: 0; padding: 0; overflow: hidden; }'
        '  iframe { border: none; width: 100%; height: 100vh; }'
        '</style>'
        f'<iframe src="{pdf_response.url}" type="application/pdf"></iframe>'
    )


def _get_claim_for_note(note_id: str) -> Claim | None:
    """Return the first Claim linked to the given note, or None."""
    return Claim.objects.filter(note__dbid=note_id).first()


class _ClaimPdfButton(ActionButton):
    """Base class for claim PDF action buttons in the note header."""

    FORM_TYPE: str = ""
    TEMPLATE: str = ""
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        """Show the button only if the note has an associated claim."""
        log.info(f"[{self.__class__.__name__}.visible] event.name={self.event.name} context={self.event.context}")
        note_id = self.event.context.get("note_id")
        if not note_id:
            log.info(f"[{self.__class__.__name__}.visible] No note_id in context, returning False")
            return False
        has_claim = Claim.objects.filter(note__dbid=note_id).exists()
        log.info(f"[{self.__class__.__name__}.visible] note_id={note_id} has_claim={has_claim}")
        return bool(has_claim)

    def handle(self) -> list[Effect]:
        """Generate a PDF and present a link in a modal."""
        note_id = self.event.context.get("note_id", "")
        claim = _get_claim_for_note(note_id)
        if not claim:
            log.warning(f"[{self.__class__.__name__}] No claim found for note {note_id}")
            content = f"{_MODAL_STYLE}<p class='error'>No claim found for this note.</p>"
        else:
            tz_name = self.secrets.get("timezone", "")
            content = _generate_pdf_modal_html(
                claim_id=str(claim.id),
                form_type=self.FORM_TYPE,
                template=self.TEMPLATE,
                tz_name=tz_name,
            )

        return [
            LaunchModalEffect(
                content=content,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title=self.BUTTON_TITLE,
            ).apply()
        ]


class SuperbillButton(_ClaimPdfButton):
    """Note header button that generates and opens a superbill PDF."""

    BUTTON_TITLE = "Superbill"
    BUTTON_KEY = "GENERATE_SUPERBILL"
    PRIORITY = 10
    FORM_TYPE = "superbill"
    TEMPLATE = "superbill.html"


class HcfaButton(_ClaimPdfButton):
    """Note header button that generates and opens a CMS-1500 (HCFA) PDF."""

    BUTTON_TITLE = "CMS-1500"
    BUTTON_KEY = "GENERATE_HCFA"
    PRIORITY = 11
    FORM_TYPE = "hcfa"
    TEMPLATE = "hcfa.html"
