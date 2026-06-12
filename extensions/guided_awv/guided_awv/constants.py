"""Shared constants for the guided_awv plugin.

Anything that needs to identify the AWV note type belongs here. Keeps
``GuidedAWVApp.visible()`` and ``PreventionPlanButton.visible()`` in sync -
prior versions drifted because the same logic lived in two places.
"""

# SNOMED CT 401131001 = "Annual wellness visit (procedure)"
# The Canvas instance must have a NoteType configured with this system + code
# for the Guided AWV button and Prevention Plan header button to appear.
AWV_SYSTEM = "SNOMED"
AWV_CODE = "401131001"


def is_awv_note_type(note_type_version: object) -> bool:
    """Return True if the given note_type_version is the AWV note type.

    Tolerates note_type_version being None or any object missing the
    expected attributes - returns False in those cases rather than raising.
    """
    if note_type_version is None:
        return False
    system = getattr(note_type_version, "system", None)
    code = getattr(note_type_version, "code", None)
    return bool(system == AWV_SYSTEM and code == AWV_CODE)
