"""Shared test fixtures for questionnaire_webhook tests."""

from unittest.mock import MagicMock

import pytest


def make_event(questionnaire_text: str, **extra_fields) -> MagicMock:
    """A QUESTIONNAIRE_COMMAND__POST_COMMIT event for the given questionnaire."""
    event = MagicMock()
    event.target.id = "questionnaire-target-1"
    event.context = {
        "note": {"id": "note-abc-123"},
        "patient": {"id": "patient-xyz-789"},
        "fields": {
            "questionnaire": {"text": questionnaire_text},
            **extra_fields,
        },
    }
    return event


@pytest.fixture
def ccm_event() -> MagicMock:
    """An RDP Encounter Type questionnaire with the CCM-eligible answer."""
    return make_event("RDP Encounter Type", **{"question-3331": 6702})


@pytest.fixture
def pa_event() -> MagicMock:
    """A PA questionnaire carrying medication fields."""
    event = make_event("PA Medication Request")
    event.context["fields"]["questionnaire"]["extra"] = {
        "questions": [
            {"label": "Drug Name", "options": [{"label": "Atorvastatin"}]},
            {"label": "Quantity", "options": [{"label": "30"}]},
            {"label": "Strength", "options": []},
            {"label": "Irrelevant Question", "options": [{"label": "ignore me"}]},
        ]
    }
    return event


@pytest.fixture
def secrets() -> dict:
    """Plugin secrets as configured in a Canvas instance."""
    return {
        "CCM_WEBHOOK_URL": "https://example.test/ccm",
        "PA_WEBHOOK_URL": "https://example.test/pa",
        "AUTH_TOKEN": "s3cret",
    }
