"""
Unit tests for the Flask application (app.py).

Tests all routes and socket.io handlers without making actual database calls.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import sys
from pathlib import Path

# Add intake_agent directory to path so relative imports work
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'intake_agent'))

# Now import the app module
from intake_agent import app as app_module


@pytest.fixture
def app():
    """Create and configure a test Flask app."""
    app_module.app.config['TESTING'] = True
    app_module.app.config['SECRET_KEY'] = 'test-secret-key'
    return app_module.app


@pytest.fixture
def client(app):
    """Create a test client for the Flask app."""
    return app.test_client()


@pytest.fixture
def socketio_client(app):
    """Create a test client for socketio."""
    return app_module.socketio.test_client(app)


class TestIndexRoute:
    """Tests for the index route (/)."""

    @patch('intake_agent.app.database.get_all_patients')
    @patch('intake_agent.app.database.get_patient_completeness')
    def test_index_with_no_patients(self, mock_completeness, mock_get_patients, client):
        """Test index page with no patients."""
        mock_get_patients.return_value = []

        response = client.get('/')

        assert response.status_code == 200
        assert b'EZGrow Patient Intake Agent' in response.data
        mock_get_patients.assert_called_once()

    @patch('intake_agent.app.database.get_all_patients')
    @patch('intake_agent.app.database.get_patient_completeness')
    def test_index_with_patients(self, mock_completeness, mock_get_patients, client):
        """Test index page with patients."""
        mock_get_patients.return_value = [
            {'id': 1, 'first_name': 'John', 'last_name': 'Doe'},
            {'id': 2, 'first_name': 'Jane', 'last_name': 'Smith'}
        ]
        mock_completeness.return_value = {'overall': 0.75}

        response = client.get('/')

        assert response.status_code == 200
        mock_get_patients.assert_called_once()
        assert mock_completeness.call_count == 2

    @patch('intake_agent.app.database.get_all_patients')
    @patch('intake_agent.app.database.get_patient_completeness')
    def test_index_includes_model_info(self, mock_completeness, mock_get_patients, client):
        """Test that index page includes model information."""
        mock_get_patients.return_value = []

        response = client.get('/')

        assert response.status_code == 200
        # Check that config.MODEL is passed to template
        assert b'claude' in response.data.lower() or b'gpt' in response.data.lower()


class TestNewPatientRoute:
    """Tests for the /patient/new route."""

    @patch('intake_agent.app.database.create_patient')
    def test_new_patient_creates_and_redirects(self, mock_create_patient, client):
        """Test creating a new patient redirects to patient page."""
        mock_create_patient.return_value = 42

        response = client.get('/patient/new', follow_redirects=False)

        assert response.status_code == 302
        assert '/patient/42' in response.location
        mock_create_patient.assert_called_once()

    @patch('intake_agent.app.database.create_patient')
    def test_new_patient_with_follow_redirects(self, mock_create_patient, client):
        """Test new patient creation with redirect following."""
        mock_create_patient.return_value = 10

        with patch('intake_agent.app.database.get_patient') as mock_get_patient:
            mock_get_patient.return_value = {'id': 10, 'first_name': None}
            with patch('intake_agent.app.database.get_patient_conditions') as mock_cond:
                with patch('intake_agent.app.database.get_patient_medications') as mock_med:
                    with patch('intake_agent.app.database.get_patient_allergies') as mock_allergy:
                        with patch('intake_agent.app.database.get_patient_goals') as mock_goals:
                            with patch('intake_agent.app.database.get_patient_messages') as mock_msg:
                                mock_cond.return_value = []
                                mock_med.return_value = []
                                mock_allergy.return_value = []
                                mock_goals.return_value = []
                                mock_msg.return_value = []

                                response = client.get('/patient/new', follow_redirects=True)

                                assert response.status_code == 200


class TestPatientPageRoute:
    """Tests for the /patient/<id> route."""

    @patch('intake_agent.app.database.get_patient')
    def test_patient_page_not_found(self, mock_get_patient, client):
        """Test patient page returns 404 for non-existent patient."""
        mock_get_patient.return_value = None

        response = client.get('/patient/999')

        assert response.status_code == 404
        assert b'Patient not found' in response.data

    @patch('intake_agent.app.database.get_patient')
    @patch('intake_agent.app.database.get_patient_conditions')
    @patch('intake_agent.app.database.get_patient_medications')
    @patch('intake_agent.app.database.get_patient_allergies')
    @patch('intake_agent.app.database.get_patient_goals')
    @patch('intake_agent.app.database.get_patient_messages')
    def test_patient_page_success(self, mock_msg, mock_goals, mock_allergy,
                                   mock_med, mock_cond, mock_get_patient, client):
        """Test successful patient page load."""
        mock_get_patient.return_value = {
            'id': 1,
            'first_name': 'John',
            'last_name': 'Doe',
            'date_of_birth': None
        }
        mock_cond.return_value = []
        mock_med.return_value = []
        mock_allergy.return_value = []
        mock_goals.return_value = []
        mock_msg.return_value = []

        response = client.get('/patient/1')

        assert response.status_code == 200
        assert b'John' in response.data
        assert b'Doe' in response.data

    @patch('intake_agent.app.database.get_patient')
    @patch('intake_agent.app.database.get_patient_conditions')
    @patch('intake_agent.app.database.get_patient_medications')
    @patch('intake_agent.app.database.get_patient_allergies')
    @patch('intake_agent.app.database.get_patient_goals')
    @patch('intake_agent.app.database.get_patient_messages')
    def test_patient_page_calculates_age_adult(self, mock_msg, mock_goals, mock_allergy,
                                                mock_med, mock_cond, mock_get_patient, client):
        """Test age calculation for adult patient."""
        mock_get_patient.return_value = {
            'id': 1,
            'first_name': 'John',
            'last_name': 'Doe',
            'date_of_birth': '1990-01-01'
        }
        mock_cond.return_value = []
        mock_med.return_value = []
        mock_allergy.return_value = []
        mock_goals.return_value = []
        mock_msg.return_value = []

        response = client.get('/patient/1')

        assert response.status_code == 200
        # Age should be calculated and displayed

    @patch('intake_agent.app.database.get_patient')
    @patch('intake_agent.app.database.get_patient_conditions')
    @patch('intake_agent.app.database.get_patient_medications')
    @patch('intake_agent.app.database.get_patient_allergies')
    @patch('intake_agent.app.database.get_patient_goals')
    @patch('intake_agent.app.database.get_patient_messages')
    def test_patient_page_with_medical_data(self, mock_msg, mock_goals, mock_allergy,
                                             mock_med, mock_cond, mock_get_patient, client):
        """Test patient page with complete medical data."""
        mock_get_patient.return_value = {
            'id': 1,
            'first_name': 'John',
            'last_name': 'Doe',
            'date_of_birth': '1990-01-01'
        }
        mock_cond.return_value = [
            {'name': 'Hypertension', 'status': 'stable', 'comment': 'Controlled'}
        ]
        mock_med.return_value = [
            {'name': 'Lisinopril', 'dose': '10mg', 'form': 'tablet'}
        ]
        mock_allergy.return_value = [
            {'name': 'Penicillin', 'comment': 'Rash'}
        ]
        mock_goals.return_value = [
            {'name': 'Lower BP', 'comment': 'Target 120/80'}
        ]
        mock_msg.return_value = []

        response = client.get('/patient/1')

        assert response.status_code == 200
        assert b'Hypertension' in response.data
        assert b'Lisinopril' in response.data


class TestGetMessagesRoute:
    """Tests for the /messages/<id> route."""

    @patch('intake_agent.app.database.get_patient_messages')
    def test_get_messages_empty(self, mock_get_messages, client):
        """Test getting messages for patient with no messages."""
        mock_get_messages.return_value = []

        response = client.get('/messages/1')

        assert response.status_code == 200
        assert response.json == []

    @patch('intake_agent.app.database.get_patient_messages')
    def test_get_messages_with_data(self, mock_get_messages, client):
        """Test getting messages for patient with messages."""
        mock_get_messages.return_value = [
            {'participant': 'patient', 'content': 'Hello'},
            {'participant': 'agent', 'content': 'Hi there!'}
        ]

        response = client.get('/messages/1')

        assert response.status_code == 200
        assert len(response.json) == 2
        assert response.json[0]['content'] == 'Hello'
        assert response.json[1]['content'] == 'Hi there!'


class TestSocketIOHandlers:
    """Tests for Socket.IO event handlers."""

    def test_connect_handler(self, socketio_client):
        """Test socket.io connect event."""
        assert socketio_client.is_connected()

    def test_disconnect_handler(self, socketio_client):
        """Test socket.io disconnect event."""
        socketio_client.disconnect()
        assert not socketio_client.is_connected()

    def test_join_room_handler(self, socketio_client):
        """Test joining a patient room."""
        socketio_client.emit('join', {'patient_id': 1})
        # Room joining is silent, just verify no errors

    def test_join_room_without_patient_id(self, socketio_client):
        """Test joining room without patient_id does nothing."""
        socketio_client.emit('join', {})
        # Should not raise an error

    @patch('intake_agent.app.database.get_patient_messages')
    @patch('intake_agent.app.database.add_message')
    @patch('intake_agent.app.intake_parser.generate_greeting')
    def test_request_greeting_for_new_patient(self, mock_greeting, mock_add_msg,
                                               mock_get_msgs, socketio_client):
        """Test requesting greeting for new patient with no messages."""
        mock_get_msgs.return_value = []
        mock_greeting.return_value = "Hello! How can I help you today?"

        # Join the room first
        socketio_client.emit('join', {'patient_id': 1})
        socketio_client.get_received()  # Clear any received messages

        # Now request greeting
        socketio_client.emit('request_greeting', {'patient_id': 1})

        received = socketio_client.get_received()
        assert len(received) > 0
        assert any(msg['name'] == 'new_message' for msg in received)

    @patch('intake_agent.app.database.get_patient_messages')
    def test_request_greeting_patient_has_messages(self, mock_get_msgs, socketio_client):
        """Test requesting greeting when patient already has messages."""
        mock_get_msgs.return_value = [
            {'participant': 'agent', 'content': 'Hello'}
        ]

        socketio_client.emit('request_greeting', {'patient_id': 1})

        # Should not send a greeting
        received = socketio_client.get_received()
        # No new_message should be emitted

    def test_request_greeting_without_patient_id(self, socketio_client):
        """Test requesting greeting without patient_id."""
        socketio_client.emit('request_greeting', {})
        # Should not raise an error

    @patch('intake_agent.app.database.add_message')
    @patch('intake_agent.app.database.get_patient_messages')
    @patch('intake_agent.app.intake_parser.extract_intake_data')
    @patch('intake_agent.app.intake_parser.generate_response')
    def test_send_message_success(self, mock_gen_response, mock_extract,
                                   mock_get_msgs, mock_add_msg, socketio_client):
        """Test sending a message successfully."""
        mock_get_msgs.return_value = [
            {'participant': 'patient', 'content': 'My name is John'}
        ]
        mock_extract.return_value = {}
        mock_gen_response.return_value = "Nice to meet you, John!"

        # Join the room first
        socketio_client.emit('join', {'patient_id': 1})
        socketio_client.get_received()  # Clear any received messages

        # Now send message
        socketio_client.emit('send_message', {
            'patient_id': 1,
            'content': 'My name is John'
        })

        received = socketio_client.get_received()
        # Should receive patient message and agent response
        assert len(received) >= 2

    @patch('intake_agent.app.database.add_message')
    def test_send_message_empty_content(self, mock_add_msg, socketio_client):
        """Test sending message with empty content does nothing."""
        socketio_client.emit('send_message', {
            'patient_id': 1,
            'content': '   '
        })

        mock_add_msg.assert_not_called()

    def test_send_message_without_patient_id(self, socketio_client):
        """Test sending message without patient_id does nothing."""
        socketio_client.emit('send_message', {
            'content': 'Hello'
        })
        # Should not raise an error

    @patch('intake_agent.app.database.add_message')
    @patch('intake_agent.app.database.get_patient_messages')
    @patch('intake_agent.app.database.update_patient')
    @patch('intake_agent.app.intake_parser.extract_intake_data')
    @patch('intake_agent.app.intake_parser.generate_response')
    def test_send_message_extracts_demographics(self, mock_gen_response, mock_extract,
                                                 mock_update, mock_get_msgs,
                                                 mock_add_msg, socketio_client):
        """Test that demographics are extracted and updated."""
        mock_get_msgs.return_value = [
            {'participant': 'patient', 'content': 'My name is John Doe'}
        ]
        mock_extract.return_value = {
            'patient_updates': {'first_name': 'John', 'last_name': 'Doe'}
        }
        mock_gen_response.return_value = "Thanks, John!"

        socketio_client.emit('send_message', {
            'patient_id': 1,
            'content': 'My name is John Doe'
        })

        mock_update.assert_called_once_with(1, first_name='John', last_name='Doe')

    @patch('intake_agent.app.database.add_message')
    @patch('intake_agent.app.database.get_patient_messages')
    @patch('intake_agent.app.database.add_condition')
    @patch('intake_agent.app.intake_parser.extract_intake_data')
    @patch('intake_agent.app.intake_parser.generate_response')
    def test_send_message_extracts_conditions(self, mock_gen_response, mock_extract,
                                               mock_add_condition, mock_get_msgs,
                                               mock_add_msg, socketio_client):
        """Test that conditions are extracted and added."""
        mock_get_msgs.return_value = [
            {'participant': 'patient', 'content': 'I have high blood pressure'}
        ]
        mock_extract.return_value = {
            'conditions': [
                {'name': 'Hypertension', 'status': 'stable', 'comment': None}
            ]
        }
        mock_gen_response.return_value = "I see you have hypertension."

        socketio_client.emit('send_message', {
            'patient_id': 1,
            'content': 'I have high blood pressure'
        })

        mock_add_condition.assert_called_once()

    @patch('intake_agent.app.database.add_message')
    @patch('intake_agent.app.database.get_patient_messages')
    @patch('intake_agent.app.database.add_medication')
    @patch('intake_agent.app.intake_parser.extract_intake_data')
    @patch('intake_agent.app.intake_parser.generate_response')
    def test_send_message_extracts_medications(self, mock_gen_response, mock_extract,
                                                mock_add_med, mock_get_msgs,
                                                mock_add_msg, socketio_client):
        """Test that medications are extracted and added."""
        mock_get_msgs.return_value = [
            {'participant': 'patient', 'content': 'I take Lisinopril 10mg'}
        ]
        mock_extract.return_value = {
            'medications': [
                {
                    'name': 'Lisinopril',
                    'dose': '10mg',
                    'form': 'tablet',
                    'sig': 'once daily',
                    'indications': 'blood pressure'
                }
            ]
        }
        mock_gen_response.return_value = "Got it, you take Lisinopril."

        socketio_client.emit('send_message', {
            'patient_id': 1,
            'content': 'I take Lisinopril 10mg'
        })

        mock_add_med.assert_called_once()

    @patch('intake_agent.app.database.add_message')
    @patch('intake_agent.app.database.get_patient_messages')
    @patch('intake_agent.app.database.get_patient')
    @patch('intake_agent.app.database.get_patient_conditions')
    @patch('intake_agent.app.database.get_patient_medications')
    @patch('intake_agent.app.database.get_patient_allergies')
    @patch('intake_agent.app.database.get_patient_goals')
    @patch('intake_agent.app.database.add_condition')
    @patch('intake_agent.app.intake_parser.extract_intake_data')
    @patch('intake_agent.app.intake_parser.generate_response')
    def test_send_message_emits_medical_record_update(
            self, mock_gen_response, mock_extract, mock_add_condition, mock_get_goals,
            mock_get_allergies, mock_get_meds, mock_get_conds, mock_get_patient,
            mock_get_msgs, mock_add_msg, socketio_client):
        """Test that medical record update is emitted when data extracted."""
        mock_get_msgs.return_value = [
            {'participant': 'patient', 'content': 'I have diabetes'}
        ]
        mock_extract.return_value = {
            'conditions': [{'name': 'Diabetes', 'status': None, 'comment': None}]
        }
        mock_gen_response.return_value = "I see."
        mock_get_patient.return_value = {'id': 1, 'first_name': 'John'}
        mock_get_conds.return_value = [{'name': 'Diabetes'}]
        mock_get_meds.return_value = []
        mock_get_allergies.return_value = []
        mock_get_goals.return_value = []

        # Join the room first
        socketio_client.emit('join', {'patient_id': 1})
        socketio_client.get_received()  # Clear any received messages

        # Now send message
        socketio_client.emit('send_message', {
            'patient_id': 1,
            'content': 'I have diabetes'
        })

        received = socketio_client.get_received()
        # Should include medical_record_update event
        assert any(msg['name'] == 'medical_record_update' for msg in received)


class TestAgeCalculation:
    """Tests for age calculation logic in patient_page."""

    @patch('intake_agent.app.database.get_patient')
    @patch('intake_agent.app.database.get_patient_conditions')
    @patch('intake_agent.app.database.get_patient_medications')
    @patch('intake_agent.app.database.get_patient_allergies')
    @patch('intake_agent.app.database.get_patient_goals')
    @patch('intake_agent.app.database.get_patient_messages')
    def test_age_calculation_infant_months_only(self, mock_msg, mock_goals, mock_allergy,
                                                  mock_med, mock_cond, mock_get_patient, client):
        """Test age calculation for infant (months only)."""
        # Calculate DOB for a 6-month-old
        today = datetime.today()
        six_months_ago = today.replace(month=today.month - 6 if today.month > 6 else today.month + 6)
        dob = six_months_ago.strftime('%Y-%m-%d')

        mock_get_patient.return_value = {
            'id': 1,
            'first_name': 'Baby',
            'last_name': 'Doe',
            'date_of_birth': dob
        }
        mock_cond.return_value = []
        mock_med.return_value = []
        mock_allergy.return_value = []
        mock_goals.return_value = []
        mock_msg.return_value = []

        response = client.get('/patient/1')

        assert response.status_code == 200
        # Should display age in months format

    @patch('intake_agent.app.database.get_patient')
    @patch('intake_agent.app.database.get_patient_conditions')
    @patch('intake_agent.app.database.get_patient_medications')
    @patch('intake_agent.app.database.get_patient_allergies')
    @patch('intake_agent.app.database.get_patient_goals')
    @patch('intake_agent.app.database.get_patient_messages')
    def test_age_calculation_invalid_date(self, mock_msg, mock_goals, mock_allergy,
                                           mock_med, mock_cond, mock_get_patient, client):
        """Test age calculation with invalid date format."""
        mock_get_patient.return_value = {
            'id': 1,
            'first_name': 'John',
            'last_name': 'Doe',
            'date_of_birth': 'invalid-date'
        }
        mock_cond.return_value = []
        mock_med.return_value = []
        mock_allergy.return_value = []
        mock_goals.return_value = []
        mock_msg.return_value = []

        response = client.get('/patient/1')

        # Should not crash, age will be None
        assert response.status_code == 200
