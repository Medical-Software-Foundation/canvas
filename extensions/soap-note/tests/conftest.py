import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_note():
    note = MagicMock()
    note.id = "note-uuid-123"
    note.dbid = 42
    note.patient.id = "patient-uuid-456"
    return note


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.query_params = {}
    return request


@pytest.fixture
def mock_questionnaire():
    q = MagicMock()
    q.id = "questionnaire-uuid-789"
    q.code = "SOAP_BRIEF_ROS"
    return q


@pytest.fixture
def mock_ros_config():
    return {
        "questions": [
            {
                "content": "Constitutional",
                "code": "91689009",
                "responses": [
                    {"name": "Fever", "code": "386661006", "value": "Fever"},
                    {"name": "Chills", "code": "274640006", "value": "Chills"},
                ],
            },
            {
                "content": "Cardiac",
                "code": "9168",
                "responses": [
                    {"name": "Chest pain", "code": "29857009", "value": "Chest pain"},
                ],
            },
        ],
    }


@pytest.fixture
def mock_exam_config():
    return {
        "questions": [
            {
                "content": "Constitutional",
                "code": "SOAP_EXAM_CONSTITUTIONAL_SYS",
                "responses": [
                    {"name": "Constitutional", "code": "SOAP_EXAM_CONSTITUTIONAL_FINDING", "value": "Alert, no acute distress."},
                ],
            },
            {
                "content": "Skin",
                "code": "SOAP_EXAM_SKIN_SYS",
                "responses": [
                    {"name": "Skin", "code": "SOAP_EXAM_SKIN_FINDING", "value": "Warm and dry."},
                ],
            },
        ],
    }
