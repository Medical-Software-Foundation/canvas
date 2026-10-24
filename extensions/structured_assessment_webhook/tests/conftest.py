"""Shared test fixtures for structured_assessment_webhook tests."""

from unittest.mock import MagicMock

import pytest


def make_event(assessment_title, **extra_fields) -> MagicMock:
    """A STRUCTURED_ASSESSMENT_COMMAND__POST_COMMIT event for the given assessment."""
    event = MagicMock()
    event.context = {
        "note": {"id": "note-abc-123"},
        "patient": {"id": "patient-xyz-789"},
        "fields": {
            "questionnaire": {"text": assessment_title},
            **extra_fields,
        },
    }
    return event


@pytest.fixture
def matching_event() -> MagicMock:
    """A Health Coaching ABT assessment carrying the CCM-eligible answer."""
    return make_event("Health Coaching ABT", **{"question-3973": 7550})


@pytest.fixture
def secrets() -> dict:
    """Plugin secrets as configured in a Canvas instance."""
    return {"WEBHOOK_URL": "https://example.test/hook", "AUTH_TOKEN": "s3cret"}
