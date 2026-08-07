"""Context for the add-to-waitlist form.

Both buttons render the same form and post to the same endpoint. They differ
only in what they pre-fill: the chart-header button knows the patient, and the
button on a cancelled appointment also knows the service, provider, and
location that just freed up.
"""

from __future__ import annotations

from typing import Any

from scheduling_waitlist.constants import API_BASE, MAX_NOTE_LENGTH
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.display import patient_name
from scheduling_waitlist.services.entries import ENTRY_RELATIONS
from scheduling_waitlist.services.html import safe_json
from scheduling_waitlist.services.options import build_options


def live_entries_for_patient(patient_dbid: Any) -> list[Any]:
    """Entries this patient is already waiting on.

    Shown so the form can offer to edit an existing request rather than let
    someone add a near-duplicate the unique index will refuse anyway.
    """
    from scheduling_waitlist.constants import MATCHABLE_STATUSES
    from scheduling_waitlist.models import WaitlistEntry

    return list(
        WaitlistEntry.objects.filter(
            patient_id=patient_dbid, status__in=list(MATCHABLE_STATUSES)
        ).select_related(*ENTRY_RELATIONS)
    )


def build_form_context(
    *,
    patient: Any | None,
    config: WaitlistConfig,
    prefill: dict[str, Any] | None = None,
    heading: str = "Add to waitlist",
    intro: str = "",
) -> dict[str, Any]:
    """Everything the form template renders.

    Every value that reaches an inline script goes through ``safe_json``: a
    location or service named with a closing script tag would otherwise break
    out of the block and run as markup.
    """
    options = build_options(config)
    patient_dbid = getattr(patient, "dbid", None)

    existing = []
    if patient_dbid is not None:
        existing = [
            {
                "dbid": getattr(entry, "dbid", None),
                "appointment_type": getattr(
                    getattr(entry, "note_type", None), "name", ""
                )
                or "Any appointment type",
                "status": getattr(entry, "status", ""),
            }
            for entry in live_entries_for_patient(patient_dbid)
        ]

    return {
        "heading": heading,
        "intro": intro,
        "patient_name": patient_name(patient),
        "max_note_length": MAX_NOTE_LENGTH,
        "config_json": safe_json(
            {
                "apiBase": API_BASE,
                "patientId": getattr(patient, "id", None),
                "options": options,
                "prefill": prefill or {},
                "existing": existing,
                "maxNoteLength": MAX_NOTE_LENGTH,
            }
        ),
    }
