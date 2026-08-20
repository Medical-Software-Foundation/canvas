"""Field validation for admin-entered resources.

Every function here returns findings rather than raising. A malformed submission
is an ordinary outcome of a form, and the routes turn these into a 400 carrying a
field-error dict the UI can render beside the offending input.
"""

from typing import Any

from patient_resources.constants import (
    ALLOWED_URL_SCHEMES,
    LABEL_MAX_CHARS,
    TITLE_MAX_CHARS,
    URL_MAX_CHARS,
)

# Anything at or below space, plus DEL. A URL containing a raw newline or tab can
# be split by a permissive parser into something other than what was reviewed.
_CONTROL_CHARS = frozenset(chr(code) for code in list(range(0x21)) + [0x7F])


def is_safe_href(value: Any) -> bool:
    """True if this string is safe to render as a link to a patient.

    Parsed by hand rather than with ``urlparse``, which is not in the sandbox's
    allowlist for ``urllib.parse`` -- only ``quote``, ``unquote`` and
    ``urlencode`` are. Importing it passes every test under CPython and then
    stops the plugin loading on the instance.

    Stricter than the equivalent check in ``patient-tags``, which this started
    from, in two ways that matter for a patient-facing library:

    * A protocol-relative URL such as ``//example.org/x`` is rejected. The
      patient-tags version splits on the first slash, finds no colon in the empty
      leading segment, and treats it as a relative path -- but a browser
      navigates offsite.
    * Relative paths are rejected outright. They are legitimate for a chart
      banner linking within Canvas; here a "public link" that resolves against
      the portal origin is either a mistake or an attempt to point patients at an
      authenticated route.

    Also called at serialize time, not only on write. Storage is not a trust
    boundary: the DDL emits no constraints, and a row may predate a fix to this
    function.
    """
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > URL_MAX_CHARS:
        return False
    if any(char in _CONTROL_CHARS for char in candidate):
        return False

    lowered = candidate.lower()
    for scheme in ALLOWED_URL_SCHEMES:
        prefix = f"{scheme}://"
        if lowered.startswith(prefix):
            rest = candidate[len(prefix) :]
            break
    else:
        # No allowed scheme. This is also what rejects "javascript:",
        # "data:", a protocol-relative "//host" and every relative path.
        return False

    # The authority runs to the first delimiter that ends it.
    authority = rest
    for delimiter in ("/", "?", "#"):
        authority = authority.split(delimiter, 1)[0]

    if not authority:
        return False
    # Credentials in the authority let a link display one host and reach another.
    if "@" in authority:
        return False
    return True


def validate_resource(title: Any, url: Any, label: Any) -> dict[str, str]:
    """Check one resource submission. Returns ``{field: message}``, empty if valid.

    Never raises, and never silently repairs a value -- an admin who pasted a
    bad link needs to see that, not to have it quietly trimmed into something
    else.
    """
    errors: dict[str, str] = {}

    clean_title = str(title or "").strip()
    if not clean_title:
        errors["title"] = "Enter a title."
    elif len(clean_title) > TITLE_MAX_CHARS:
        errors["title"] = f"Keep the title to {TITLE_MAX_CHARS} characters or fewer."

    clean_url = str(url or "").strip()
    if not clean_url:
        errors["url"] = "Enter a link."
    elif len(clean_url) > URL_MAX_CHARS:
        errors["url"] = f"Keep the link to {URL_MAX_CHARS} characters or fewer."
    elif not is_safe_href(clean_url):
        errors["url"] = "Enter a full public web address starting with http:// or https://."

    clean_label = str(label or "").strip()
    if len(clean_label) > LABEL_MAX_CHARS:
        errors["label"] = f"Keep the label to {LABEL_MAX_CHARS} characters or fewer."

    return errors


def normalize_resource(title: Any, url: Any, label: Any) -> dict[str, str]:
    """The trimmed values to store, once ``validate_resource`` has passed."""
    return {
        "title": str(title or "").strip(),
        "url": str(url or "").strip(),
        "label": str(label or "").strip(),
    }
