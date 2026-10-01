"""Pure helper functions with no Canvas dependencies, so they can be unit tested
without a running instance."""

DEFAULT_CHART_REVIEW_NOTE_TYPE_NAME = "Chart Review"


def is_chart_review_note_type(note_type_name, configured_name):
    """Return True when a note type name should be treated as a Chart Review note.

    Matching is case-insensitive and ignores surrounding whitespace so small
    differences in how the note type is labelled on an instance still match. If no
    configured name is provided, we fall back to the default "Chart Review".
    """
    if not note_type_name:
        return False

    target = (configured_name or DEFAULT_CHART_REVIEW_NOTE_TYPE_NAME).strip().lower()
    if not target:
        target = DEFAULT_CHART_REVIEW_NOTE_TYPE_NAME.strip().lower()

    return note_type_name.strip().lower() == target


def staff_display_name(staff):
    """Best-effort human-readable name for a Staff record for the picker."""
    credentialed = getattr(staff, "credentialed_name", None)
    if credentialed:
        return credentialed
    full = getattr(staff, "full_name", None)
    if full:
        return full
    first = (getattr(staff, "first_name", "") or "").strip()
    last = (getattr(staff, "last_name", "") or "").strip()
    name = f"{first} {last}".strip()
    return name or "Unknown staff"


def staff_subtitle(staff):
    """Best-effort secondary line for a Staff option (role / specialty).

    Falls back to the role abbreviation, then to an empty string, so a staff
    member with no clinical role still renders.
    """
    clinical_role = getattr(staff, "top_clinical_role", None)
    role_name = getattr(clinical_role, "name", None)
    if role_name:
        return role_name

    abbr = getattr(staff, "top_role_abbreviation", None)
    if abbr:
        return abbr

    return ""


def initials(name):
    """Return up to two uppercase initials from a display name (e.g. 'CP')."""
    if not name:
        return "?"
    parts = [p for p in name.replace(",", " ").split() if p]
    # Skip a trailing credential token (e.g. "MD") when computing initials.
    letters = [p[0] for p in parts if p[0].isalpha()]
    if not letters:
        return "?"
    return "".join(letters[:2]).upper()
