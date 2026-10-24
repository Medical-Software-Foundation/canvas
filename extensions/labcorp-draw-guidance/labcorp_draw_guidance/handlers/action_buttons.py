from html import escape

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from labcorp_draw_guidance.domain.order_resolution import OrderGuidance, resolve_note_guidances

BUTTON_KEY = "LABCORP_DRAW_GUIDANCE"


class LabOrderDrawGuidanceButton(ActionButton):
    """Surfaces Labcorp tube/draw guidance for lab orders staged on the current note.

    Always shown in the note header (no conditional visibility -- clinicians
    can rely on it being in the same place on every note). Clicking it opens
    the consolidated tube type/count/volume breakdown for the note's lab
    order(s) in the right chart pane, or a friendly message if the note has
    no lab order with known guidance yet.

    This plugin never touches the printed requisition or specimen label --
    Canvas has no hook for that -- it's an adjacent advisory surface only.
    """

    BUTTON_TITLE = "🧪 AccuDraw"
    BUTTON_KEY = BUTTON_KEY
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER
    # High value so this button sorts after other plugins' note-header
    # buttons (lower PRIORITY values appear first; unset means unordered).
    PRIORITY = 9999

    def handle(self) -> list[Effect]:
        """Open the consolidated tube breakdown for the note's lab order(s)."""
        note_dbid = self.event.context.get("note_id")
        guidances = resolve_note_guidances(note_dbid) if note_dbid is not None else []

        return [
            LaunchModalEffect(
                content=_build_panel_html(guidances),
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            ).apply()
        ]


def _build_panel_html(guidances: list[OrderGuidance]) -> str:
    """Build a small, self-contained HTML fragment for the right chart pane."""
    if not guidances:
        return (
            "<div style='font-family: sans-serif; padding: 16px;'>"
            "No AccuDraw guidance currently available for this note."
            "</div>"
        )

    sections = "".join(_build_order_section_html(guidance) for guidance in guidances)
    return (
        "<div style='font-family: -apple-system, sans-serif; padding: 16px; color-scheme: light dark;'>"
        "<h2 style='font-size: 16px; margin: 0 0 12px 0;'>Labcorp AccuDraw</h2>"
        f"{sections}"
        "</div>"
    )


def _build_order_section_html(guidance: OrderGuidance) -> str:
    """Build the HTML for a single order's tube breakdown."""
    rows = "".join(
        "<div style='padding: 10px 0; border-bottom: 1px solid rgba(128,128,128,0.3);'>"
        f"<strong>{tube.tube_count}&times; {escape(tube.tube_type)}</strong><br>"
        f"<span style='font-size: 13px; opacity: 0.8;'>"
        f"Draw volume: {tube.draw_volume_ml} mL &mdash; Covers: {escape(', '.join(tube.tests))}"
        "</span>"
        "</div>"
        for tube in guidance.consolidated
    )

    unresolved = ""
    if guidance.unresolved_test_names:
        names = escape(", ".join(guidance.unresolved_test_names))
        unresolved = (
            "<div style='margin-top: 10px; padding: 10px; border-radius: 6px; "
            "background: rgba(240, 180, 30, 0.15); font-size: 13px;'>"
            f"No bundled AccuDraw guidance yet for: {names}. Check the Health Gorilla "
            "requisition/portal for these tests."
            "</div>"
        )

    return f"<div style='margin-bottom: 16px;'>{rows}{unresolved}</div>"
