import json
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string

from patient_tags.constants import (
    BANNER_NARRATIVE_MAX_CHARS,
    DEFAULT_SEPARATOR,
    DESCRIPTION_MAX_CHARS,
    PALETTE,
    PLUGIN_NAME,
    VALID_INTENTS,
    VALID_PLACEMENTS,
    VALID_RULE_ACTIONS,
)
from patient_tags.services.label_service import (
    get_patient_assignment_ids,
    list_banner_groups,
    list_labels,
)


def _safe_json(value: Any) -> str:
    """Serialize as JSON with HTML-unsafe characters escaped to unicode.

    `json.dumps()` does not escape `<`, `>`, or `&`, so embedding its output
    directly in an inline `<script>` block lets a stored value containing
    `</script>` close the tag and execute attacker-controlled HTML/JS. The
    `\\u003c` / `\\u003e` / `\\u0026` escapes are valid JSON, decode back to
    the original characters at JS parse time, and never produce a literal
    `</script>` for the HTML tokenizer to act on.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


class PatientTagButton(ActionButton):
    """Button in patient chart header that opens the patient tag modal."""

    BUTTON_KEY = "patient_tags_button"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    @property
    def BUTTON_TITLE(self) -> str:  # noqa: N802 — overrides SDK class attr
        # Short title — Canvas truncates the rendered button text and the count
        # got cut off with "Patient Tags (N)". "Tags (N)" stays fully visible.
        count = len(get_patient_assignment_ids(self.event.target.id))
        return f"Tags ({count})" if count else "Tags"

    @property
    def BUTTON_BACKGROUND_COLOR(self) -> str:  # noqa: N802 — overrides SDK class attr
        # Yellow when the patient has assigned tags, neutral gray when none —
        # quick visual cue at the patient-header level.
        if get_patient_assignment_ids(self.event.target.id):
            return "#feff86"
        return "#e5e7eb"

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id

        labels = list_labels()
        groups = list_banner_groups()
        assigned_ids = get_patient_assignment_ids(patient_id)

        html = render_to_string(
            "templates/tag_modal.html",
            {
                "patient_id": patient_id,
                "labels_json": _safe_json(labels),
                "groups_json": _safe_json(groups),
                "assigned_ids_json": _safe_json(assigned_ids),
                "palette_json": _safe_json(PALETTE),
                "valid_intents_json": _safe_json(VALID_INTENTS),
                "valid_placements_json": _safe_json(VALID_PLACEMENTS),
                "valid_rule_actions_json": _safe_json(VALID_RULE_ACTIONS),
                "default_separator": DEFAULT_SEPARATOR,
                "description_max_chars": DESCRIPTION_MAX_CHARS,
                "banner_narrative_max_chars": BANNER_NARRATIVE_MAX_CHARS,
                "api_base": f"/plugin-io/api/{PLUGIN_NAME}",
            },
        )

        modal = LaunchModalEffect(
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            content=html,
        )
        return [modal.apply()]
