"""Shared constants for the consent_capture plugin.

The consent coding (system / code / display) and the statement text are all
configured through plugin variables (see CANVAS_MANIFEST.json) so they can be
changed without editing code. There is intentionally NO built-in default
statement text — when the statement is not configured, the plugin still works
and simply omits the statement (a neutral note is shown in the modal instead).
"""

# Button appearance
BUTTON_TITLE = "Consent"
BUTTON_KEY = "COLLECT_CONSENT"
BUTTON_COLOR = "#c0392b"  # red

# Shown in the modal (in place of the statement) when no statement is configured.
NO_STATEMENT_NOTE = "Review the consent with the patient before recording."

# Consent states in the read-only PatientConsent model that count as "already
# accepted" (so the button is hidden).
ACCEPTED_STATES = ("accepted", "accepted_via_patient_portal")


def parse_statement(raw):
    """Turn a configured statement string into a list of paragraphs.

    Each line break starts a new paragraph, so text pasted straight from a
    document keeps its paragraph structure. Blank lines are ignored, and ``||``
    also works as a separator when the configuration field only allows a single
    line. Returns an empty list when nothing is configured — there is no
    built-in default statement.
    """
    if not raw or not raw.strip():
        return []

    text = raw.replace("||", "\n").replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in text.split("\n") if line.strip()]
