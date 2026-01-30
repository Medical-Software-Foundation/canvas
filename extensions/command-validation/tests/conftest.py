"""Shared test fixtures for command-validation plugin."""

import pytest
from unittest.mock import Mock

from canvas_sdk.events import EventType


@pytest.fixture
def mock_event():
    """Factory fixture to create mock events with configurable target."""
    def _create_event(command_id: str = "test-command-id"):
        event = Mock()
        event.type = EventType.QUESTIONNAIRE_COMMAND__PRE_COMMIT
        event.target = Mock()
        event.target.id = command_id
        event.context = {
            "fields": {
                "questionnaire": {},
                "result": ""
            },
            "note": {"uuid": "test-note-id"},
            "patient": {"id": "test-patient-id"},
        }
        return event
    return _create_event


@pytest.fixture
def mock_interview():
    """Factory fixture to create mock interview with questions and responses."""
    def _create_interview(question_ids: list, answered_ids: list, question_names: dict = None):
        if question_names is None:
            question_names = {qid: f"Question {qid}" for qid in question_ids}

        interview = Mock()

        # Mock questionnaire
        questionnaire = Mock()
        questionnaire.questions.values_list.return_value = question_ids
        questionnaire.questions.filter.return_value.values_list.return_value = [
            question_names.get(qid, f"Question {qid}")
            for qid in question_ids if qid not in answered_ids
        ]

        interview.questionnaires.first.return_value = questionnaire

        # Mock interview responses
        interview.interview_responses.values_list.return_value = answered_ids

        return interview
    return _create_interview
