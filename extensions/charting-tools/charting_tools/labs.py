"""The patient's preferred lab, from patient metadata.

Lab orders this plugin creates are created with the lab already set, rather
than set by a later edit. A lab set by an edit right after a command is added
can be overwritten in an open note by a copy of the command from before the
edit, so the lab shows empty until the page is reloaded.
"""

from typing import Any

from canvas_sdk.v1.data.lab import LabPartner
from canvas_sdk.v1.data.patient import PatientMetadata

# Patient metadata naming the patient's lab, matched to a lab partner's name.
PREFERRED_LAB_KEY = "preferred_lab"


def preferred_lab_partner_id(patient_id: Any) -> str | None:
    """The id of the active lab partner named in the patient's ``preferred_lab``.

    Matched by name, ignoring capitals and surrounding spaces. None when the
    patient has no preferred lab or it names no active lab partner.
    """
    if not patient_id:
        return None
    value = (
        PatientMetadata.objects.filter(patient_id=patient_id, key=PREFERRED_LAB_KEY)
        .values_list("value", flat=True)
        .first()
    )
    wanted = str(value or "").strip().casefold()
    if not wanted:
        return None
    for partner_id, name in LabPartner.objects.filter(active=True).values_list("id", "name"):
        if str(name or "").strip().casefold() == wanted:
            return str(partner_id)
    return None
