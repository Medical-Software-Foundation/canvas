"""Shared fixtures and helpers for unstructured_med_flag tests."""

from unittest.mock import MagicMock

FDB = "http://www.fdbhealth.com/"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
UNSTRUCTURED = "http://snomed.info/sct"  # any non-drug-code system; treated as unstructured


def make_med(med_id, systems):
    """Build a medication context dict with one coding per system in `systems`.

    `systems` is a list of system URL strings. An empty list produces a med
    with an empty codings list (an unstructured med).
    """
    return {
        "id": med_id,
        "codings": [
            {"code": str(med_id), "system": system, "display": f"med-{med_id}"}
            for system in systems
        ],
    }


def make_handler(context):
    """Create a Medications handler with the given event context."""
    from unstructured_med_flag.handlers.medications import Medications

    event = MagicMock()
    event.target.id = "patient-123"
    event.context = context
    return Medications(event=event)
