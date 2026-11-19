"""The attestation prose, in one place.

These four strings were written twice before this module existed — once in
``api/handlers.py`` as ``ATTESTATION_TEMPLATES`` (substituted with
``str.replace``) and once in ``protocols/cosign_button.py`` as an inline list
built with f-strings. Two copies of the same legal attestation, interpolated
two different ways, is a divergence waiting to happen; the summary page would
have made it three.

Kept free of any Canvas SDK import so it is unit-testable outside the sandbox.
"""

from __future__ import annotations

#: Substituted with the supervisee's name. Written as a bare token rather than
#: a ``{}`` format slot because the sandbox blocks ``str.format``/``format_map``,
#: and as ``{{...}}`` rather than ``{...}`` for symmetry with the original
#: ``api/handlers.py`` spelling that callers may have in front of them.
SUPERVISEE_PLACEHOLDER = "{{supervisee}}"

#: Pre-selected in both attestation UIs and used as the server-side fallback.
#: "Reviewed & agree" is the ordinary case; the teaching-physician attestation
#: makes a stronger claim (present for the key portions) and should be a
#: deliberate choice, not what you get by not choosing. Kept separate from the
#: order of TEMPLATE_DEFS, which stays clinical rather than frequency-based.
DEFAULT_TEMPLATE_KEY = "reviewed"

#: The fallback used when a supervisee's name can't be resolved. Reads as
#: English in every template above.
DEFAULT_SUPERVISEE_NAME = "the provider"

#: key -> (menu label, template text). ``custom`` is deliberately last and
#: deliberately empty: it is the "write your own" escape hatch, and an empty
#: body makes the textarea the only source of truth for that choice.
TEMPLATE_DEFS = (
    (
        "teaching",
        "Teaching physician - present & participated",
        "I was present for and participated in the critical and key portions of "
        "the examination and agree with " + SUPERVISEE_PLACEHOLDER + "'s findings "
        "and treatment plan.",
    ),
    (
        "reviewed",
        "Reviewed & agree",
        "I have reviewed " + SUPERVISEE_PLACEHOLDER + "'s documentation and agree "
        "with the assessment, findings, and plan as documented.",
    ),
    (
        "personally_performed",
        "Personally performed",
        "I personally performed the service. I have reviewed and agree with "
        "the documentation.",
    ),
    (
        "custom",
        "Custom (write your own)",
        "",
    ),
)

#: key -> template text, for the server-side resolution path. ``custom`` is
#: excluded: an empty template is not a fallback, it is a prompt to type.
ATTESTATION_TEMPLATES = {
    key: text for (key, _label, text) in TEMPLATE_DEFS if text
}


def fill_supervisee(text: str, supervisee_name: str) -> str:
    """``text`` with the supervisee placeholder replaced."""
    name = (supervisee_name or "").strip() or DEFAULT_SUPERVISEE_NAME
    return (text or "").replace(SUPERVISEE_PLACEHOLDER, name)


def attestation_options(supervisee_name: str) -> list[dict]:
    """The picker's options, already substituted, for a rendered page.

    Substitution happens here rather than in the browser because both callers
    render through Django, which strips ``{{ }}`` out of the output — a
    placeholder that survives to the client arrives as an empty string.
    """
    options = []
    for key, label, text in TEMPLATE_DEFS:
        options.append(
            {
                "key": key,
                "label": label,
                "text": fill_supervisee(text, supervisee_name) if text else "",
            }
        )
    return options


def resolve_attestation(template_key: str, custom_text: str, supervisee_name: str) -> str:
    """The attestation body to save.

    The supervisor's edited text wins whenever it is non-empty. The modal lets
    them edit the textarea after picking a template, so discarding those edits
    in favour of the canonical string would silently sign something they did
    not write. The template is only a fallback for an empty box.
    """
    text = (custom_text or "").strip()
    if text:
        return text
    template = ATTESTATION_TEMPLATES.get(template_key)
    if not template:
        return ""
    return fill_supervisee(template, supervisee_name)
