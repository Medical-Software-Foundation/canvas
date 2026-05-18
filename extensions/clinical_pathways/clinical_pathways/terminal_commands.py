"""Terminal command catalog.

A pathway's leaves are *terminal nodes* — each references one of the plugin's
own `CustomCommand` schemas and supplies a parameter map. Each schema below
declares the user-facing name, the underlying `schema_key` (also declared in
`CANVAS_MANIFEST.json` under `components.commands`), and the configurable
fields the builder UI exposes.

Field values support `{{questionnaire.question.response}}`-style references
that the runtime evaluator resolves against captured interview responses.
"""

from __future__ import annotations

from typing import Any

# Authoritative spec for each terminal command. Keep the `schema_key` in sync
# with `CANVAS_MANIFEST.json` -> components.commands.
TERMINAL_COMMANDS: dict[str, dict[str, Any]] = {
    "pathway_classification": {
        "schema_key": "pathwayClassification",
        "name": "Pathway Classification",
        "section": "plan",
        "description": (
            "Free-text classification + recommendation. Fields support {{...}} "
            "references to questions answered earlier in this pathway arm."
        ),
        "fields": [
            {
                "key": "title",
                "label": "Title",
                "type": "text",
                "required": True,
            },
            {
                "key": "severity",
                "label": "Severity",
                "type": "select",
                "required": False,
                "options": [
                    {"value": "", "label": "(none)"},
                    {"value": "minor", "label": "Minor"},
                    {"value": "moderate", "label": "Moderate"},
                    {"value": "severe", "label": "Severe"},
                    {"value": "critical", "label": "Critical"},
                ],
            },
            {
                "key": "body",
                "label": "Body",
                "type": "textarea",
                "required": True,
            },
            {
                "key": "recommended_action",
                "label": "Recommended action",
                "type": "textarea",
                "required": False,
            },
        ],
    },
}


def terminal_command_catalog() -> list[dict[str, Any]]:
    """Serializable list shape for `/catalog/terminal-commands`."""
    return [
        {
            "key": key,
            "schema_key": spec["schema_key"],
            "name": spec["name"],
            "description": spec["description"],
            "fields": spec["fields"],
        }
        for key, spec in TERMINAL_COMMANDS.items()
    ]
