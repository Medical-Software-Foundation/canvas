"""GuidedAWVApp - NoteApplication for AWV note types only."""

from html import escape as html_escape

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication
from logger import log


class GuidedAWVApp(NoteApplication):
    """NoteApplication that renders the guided AWV workflow.

    Only visible on the Annual Wellness Visit note type, identified by
    SNOMED 401131001 (see ``guided_awv.constants``). The provider chooses
    Initial (G0438) vs Subsequent (G0439) via a toggle in the modal
    header; the choice is persisted per-note in the plugin form-state
    cache.
    """

    NAME = "Annual Wellness Visit"
    IDENTIFIER = "guided_awv__guided_awv"

    def visible(self) -> bool:
        """Show only on the AWV note type (SNOMED 401131001)."""
        note_dbid = self.event.context.get("note_id")
        if not note_dbid:
            return False
        try:
            from canvas_sdk.v1.data.note import Note

            from guided_awv.constants import is_awv_note_type

            note = Note.objects.select_related("note_type_version").get(dbid=note_dbid)
            return is_awv_note_type(note.note_type_version)
        except Exception:
            return False

    def handle(self) -> list[Effect]:
        """Build and return the guided AWV UI."""
        log.info("[GuidedAWVApp] handle called")

        note_dbid = self.event.context.get("note_id")
        patient_id = self.event.context.get("patient_id", "") or str(self.event.target.id or "")

        log.info(f"[GuidedAWVApp] note_dbid={note_dbid}, patient_id={patient_id}")

        # Look up the note UUID
        note_uuid = ""
        if note_dbid:
            try:
                from canvas_sdk.v1.data.note import Note
                note = Note.objects.get(dbid=note_dbid)
                note_uuid = str(note.id)
                log.info(f"[GuidedAWVApp] note_uuid={note_uuid}")
            except Exception as e:
                log.warning(f"[GuidedAWVApp] Error loading note: {e}")

        # Restore the provider's prior Initial/Subsequent choice from form-state
        # cache. Defaults to "initial" on first open.
        awv_type = "initial"
        if note_uuid:
            try:
                from guided_awv.api.awv_api import _get_all_form_states
                sections = _get_all_form_states(note_uuid)
                saved = (sections.get("_awv_meta") or {}).get("awv_type")
                if saved in ("initial", "subsequent"):
                    awv_type = saved
            except Exception as e:
                log.warning(f"[GuidedAWVApp] Error reading awv_type from cache: {e}")

        awv_code = "G0438" if awv_type == "initial" else "G0439"
        awv_label = f"{'Initial' if awv_type == 'initial' else 'Subsequent'} AWV ({awv_code})"
        initial_checked = "checked" if awv_type == "initial" else ""
        subsequent_checked = "checked" if awv_type == "subsequent" else ""

        # Build module sections
        modules_html = ""
        try:
            from guided_awv.modules import ALL_MODULES
            for module_class in ALL_MODULES:
                try:
                    module = module_class(  # type: ignore[abstract]
                        note_id=note_uuid,
                        patient_id=patient_id,
                        awv_type=awv_type,
                    )
                    if not module.is_visible():
                        continue
                    rendered = module.render()
                    section_id = rendered["section_id"]
                    title = rendered["title"]
                    content_html = module.render_content_html()
                    modules_html += f"""
        <div class="awv-section" id="section-{section_id}">
          <div class="awv-section-header" onclick="toggleSection('{section_id}')">
            <span class="awv-section-toggle">+</span>
            <span class="awv-section-title">{title}</span>
            <span class="awv-section-last-saved" id="last-saved-{section_id}"></span>
            <span class="awv-section-status" id="status-{section_id}"></span>
          </div>
          <div class="awv-section-body" id="body-{section_id}" style="display:none;">
            <form onsubmit="return false;">
            {content_html}
            </form>
          </div>
        </div>"""
                except Exception as e:
                    log.error(f"[GuidedAWVApp] Error in {module_class.__name__}: {e}")
                    # Escape exception text - it ends up in the modal HTML.
                    safe_err = html_escape(str(e))
                    safe_cls = html_escape(module_class.__name__)
                    modules_html += f'<div class="awv-alert awv-alert--error">Error loading {safe_cls}: {safe_err}</div>'
        except Exception as e:
            log.error(f"[GuidedAWVApp] Error loading modules: {e}")
            modules_html = f'<div class="awv-alert awv-alert--error">Error loading modules: {html_escape(str(e))}</div>'

        from canvas_sdk.templates import render_to_string
        template = render_to_string("templates/guided_awv.html")
        html = (
            template
            .replace("[[awv_label]]", awv_label)
            .replace("[[modules_html]]", modules_html)
            .replace("[[note_uuid]]", note_uuid)
            .replace("[[patient_id]]", patient_id)
            .replace("[[awv_type]]", awv_type)
            .replace("[[initial_checked]]", initial_checked)
            .replace("[[subsequent_checked]]", subsequent_checked)
        )

        return [LaunchModalEffect(
            target=LaunchModalEffect.TargetType.NOTE,
            content=html,
            title="Guided AWV",
        ).apply()]
