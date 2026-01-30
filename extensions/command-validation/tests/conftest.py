"""Shared test fixtures for command-validation plugin."""

import pytest
from unittest.mock import Mock

from canvas_sdk.events import EventType


@pytest.fixture
def mock_event():
    """Factory fixture to create mock events with configurable target."""
    def _create_event(command_id: str = "test-command-id"):
        event = Mock()
        event.type = EventType.QUESTIONNAIRE_COMMAND__POST_VALIDATION
        event.target = Mock()
        event.target.id = command_id
        return event
    return _create_event


@pytest.fixture
def mock_command_data():
    """Factory fixture to create mock command data with questionnaire responses."""
    def _create_data(questions: list, responses: dict):
        """
        Args:
            questions: List of question dicts with 'pk', 'name', 'type', 'label'
            responses: Dict of question_name -> response value
        """
        return {
            "result": "",
            "questionnaire": {
                "text": "Test Questionnaire",
                "extra": {
                    "pk": 1,
                    "name": "Test Questionnaire",
                    "questions": questions,
                },
                "value": 1,
            },
            **responses
        }
    return _create_data


def create_question(pk: int, name: str, question_type: str, label: str) -> dict:
    """Helper to create a question definition."""
    return {
        "pk": pk,
        "name": name,
        "type": question_type,
        "label": label,
        "coding": {"code": "test", "system": "test"},
        "options": [],
    }
