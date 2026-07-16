"""Shared constants for the consent_capture plugin.

The consent coding (system / code / display) and the statement text are all
configured through plugin variables (see CANVAS_MANIFEST.json) so they can be
changed without editing code. There is intentionally NO built-in default
statement text — when the statement is not configured, the plugin still works
and simply omits the statement (a neutral note is shown in the modal instead).
"""

# Button appearance. The chart-header "Consents" button is always shown for a
# patient in context; its color signals status. It goes RED (background + white
# text) only for an active, non-deceased patient with a required consent still due;
# otherwise it is a neutral gray chip (light-gray background, dark slate text) — the
# default for satisfied patients and for every inactive/deceased patient. A gray
# fill (rather than white) is used because action buttons have no border, so a white
# button would blend into the chart header.
BUTTON_TITLE = "Consents"
BUTTON_KEY = "COLLECT_CONSENT"
BUTTON_DUE_BACKGROUND = "#c0392b"  # red — a required consent is due
BUTTON_DUE_TEXT = "#ffffff"        # white text on the red button
BUTTON_SATISFIED_BACKGROUND = "#e5e7eb"  # neutral light gray — nothing due (or ineligible)
BUTTON_SATISFIED_TEXT = "#1f2933"        # dark slate text on the gray button

# Shown in the modal (in place of the statement) when no statement is configured.
NO_STATEMENT_NOTE = "Review the consent with the patient before recording."

# Chart banner shown when the patient has a required consent not on file. Shared by
# the event-driven ConsentBanner handler and the admin backfill endpoint so the key
# (used to add/remove the same alert) and copy stay in sync. Max 90 chars, no em dash.
BANNER_KEY = "consent_capture_required"
BANNER_NARRATIVE = "Required consent not on file."

# Values (case-insensitive) that turn the banner feature OFF via the
# CONSENT_BANNERS_ENABLED plugin variable. Anything else — including unset/empty —
# leaves banners enabled, so the feature is opt-out (defaults to on).
_BANNERS_OFF_VALUES = {"false", "0", "no", "off", "disabled", "n"}


def banners_enabled(raw):
    """Whether the required-consent banner should be surfaced at all.

    Reads the ``CONSENT_BANNERS_ENABLED`` plugin variable (passed through the
    handler's ``secrets``). Defaults to enabled: only an explicit off value
    (``false`` / ``0`` / ``no`` / ``off`` / ``disabled``) disables banners, so an
    unset or empty variable keeps today's behavior."""
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if not text:
        return True
    return text not in _BANNERS_OFF_VALUES

# Consent states in the read-only PatientConsent model that count as "already
# accepted" (so the consent is treated as on file).
ACCEPTED_STATES = ("accepted", "accepted_via_patient_portal")

# How a consent may be obtained. Hard-coded, fixed set of three. Each consent is
# configured (in Consent Settings) with which of these it supports; the provider
# picks one at capture. "Written" is special — see ``method_generates_pdf``.
METHOD_OPTIONS = ("Verbal", "Electronic", "Written", "Other")

# Legacy free-text values that map onto a canonical option (older configs stored
# "Electronic Form"). Both keys and values are lower-cased canonical keys.
_METHOD_ALIASES = {"electronic form": "electronic"}

# Default coding system pre-filled for new consents and used when seeding.
DEFAULT_SYSTEM = "INTERNAL"

# A "Written" consent attaches a provider-supplied document (uploaded or camera-
# captured, assembled into a single PDF in the browser). Bounds/validation for it.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MB decoded
PDF_MAGIC = b"%PDF-"


def method_generates_pdf(method):
    """Whether recording with ``method`` should generate a consent PDF.

    "Written" consents are signed on paper (or an external document), so the
    plugin does not generate a PDF — the provider uploads the signed document to
    the chart themselves. Every other method (and no method at all) gets a PDF.
    """
    return (method or "").strip().lower() != "written"


def normalize_method_options(raw):
    """Clean a list of per-consent method options down to the canonical set.

    Keeps only values that match one of ``METHOD_OPTIONS`` (case-insensitive),
    maps known legacy aliases (e.g. "Electronic Form" -> "Electronic"), returns
    them in canonical order, and de-duplicates. Returns a list (possibly empty —
    callers fall back to ``METHOD_OPTIONS``).
    """
    if not isinstance(raw, (list, tuple)):
        return []
    canonical = {opt.lower(): opt for opt in METHOD_OPTIONS}
    chosen = set()
    for item in raw:
        key = str(item or "").strip().lower()
        key = _METHOD_ALIASES.get(key, key)
        if key in canonical:
            chosen.add(canonical[key])
    # Preserve canonical order regardless of input order.
    return [opt for opt in METHOD_OPTIONS if opt in chosen]

def normalize_satisfied_by(raw):
    """Clean a list of equivalent codings down to ``[{system, code, display}]``.

    Each item identifies a Patient Consent Coding that, when on file, counts as this
    consent already being on file. Identity is the ``(system, code)`` pair; ``code``
    may be empty (some codings carry their identity entirely in ``system``), so an
    entry is kept as long as it has a ``system`` or a ``code``. Values are trimmed,
    ``display`` is preserved as a label, and entries are de-duplicated on the
    ``(system, code)`` pair (first occurrence wins). Returns a list (possibly empty).
    """
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        system = str(item.get("system") or "").strip()
        code = str(item.get("code") or "").strip()
        if not system and not code:
            continue  # no identity at all
        pair = (system, code)
        if pair in seen:
            continue
        seen.add(pair)
        out.append(
            {
                "system": system,
                "code": code,
                "display": str(item.get("display") or "").strip(),
            }
        )
    return out


# Default capacity-statement templates, pre-filled into the capacity fields on the
# Consent Settings page. ``[Patient name]`` / ``[Name]`` are substituted at capture
# time; see ``render_capacity``.
DEFAULT_CAPACITY_PATIENT = "[Patient name] has the capacity for decision-making."
DEFAULT_CAPACITY_REPRESENTATIVE = (
    "Consent obtained by [Name], who has the authority for decision-making."
)


def render_capacity(template, patient_name="", representative_name=""):
    """Fill a capacity-statement template.

    Replaces the ``[Patient name]`` and ``[Name]`` placeholders with the given
    names. Returns an empty string when the template is empty. Extra whitespace
    is collapsed so the result prints cleanly on one line.
    """
    if not template or not template.strip():
        return ""
    text = template.replace("[Patient name]", patient_name or "")
    text = text.replace("[Name]", representative_name or "")
    return " ".join(text.split())


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
