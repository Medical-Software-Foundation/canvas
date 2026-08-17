"""Finding a patient to add to the waitlist.

The roster is practice-wide, so adding someone starts by naming them. This is
the only place the plugin reads patients it has no waitlist entry for, and it is
deliberately narrow: a minimum query length, a hard result cap, and no field
beyond what the picker shows.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import Patient
from django.db.models import Q

from scheduling_waitlist.constants import (
    MAX_PATIENT_SEARCH_RESULTS,
    MIN_PATIENT_SEARCH_LENGTH,
)
from scheduling_waitlist.services.display import patient_name


def search_patients(term: str) -> list[dict[str, Any]]:
    """Active patients whose first or last name contains ``term``.

    One query with an OR rather than a query per name field: a scheduler types
    "smith" without saying which field it belongs to, and merging two result
    sets in Python would cost a second round trip and break the cap.

    Returns ``[]`` for a query below the minimum length, so a caller that
    forwards keystrokes cannot scan the whole patient table on one character.
    """
    cleaned = (term or "").strip()
    if len(cleaned) < MIN_PATIENT_SEARCH_LENGTH:
        return []

    matches = (
        Patient.objects.filter(
            Q(first_name__icontains=cleaned) | Q(last_name__icontains=cleaned),
            active=True,
        )
        .order_by("last_name", "first_name", "dbid")[:MAX_PATIENT_SEARCH_RESULTS]
    )

    return [
        {
            "id": str(getattr(patient, "id", "") or ""),
            "name": patient_name(patient),
            "birth_date": _iso_date(getattr(patient, "birth_date", None)),
        }
        for patient in matches
    ]


def _iso_date(value: Any) -> str:
    """A date as ``YYYY-MM-DD``, or an empty string.

    Formatted here rather than in the browser so the picker never has to guess
    at a locale, and so a missing date of birth renders as nothing rather than
    "None".
    """
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
