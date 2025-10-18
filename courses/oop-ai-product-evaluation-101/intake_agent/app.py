"""
Flask application for EZGrow Patient Intake Agent.
"""

from flask import Flask, render_template, redirect, url_for, request, jsonify
from flask_socketio import SocketIO, emit, join_room
import database
import intake_parser
import os
import sys
from pathlib import Path

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'
socketio = SocketIO(app, cors_allowed_origins="*")


@app.route('/')
def index():
    """
    Home page showing list of existing patients and button to create new patient.
    """
    patients = database.get_all_patients()

    # Add completeness data for each patient
    for patient in patients:
        patient['completeness'] = database.get_patient_completeness(patient['id'])

    return render_template('index.html', patients=patients)


@app.route('/patient/new')
def new_patient():
    """
    Create a new patient and redirect to their page.
    """
    patient_id = database.create_patient()
    return redirect(url_for('patient_page', patient_id=patient_id))


@app.route('/patient/<int:patient_id>')
def patient_page(patient_id):
    """
    Patient intake page showing medical record and chat interface.

    Args:
        patient_id: The patient's ID
    """
    patient = database.get_patient(patient_id)

    if not patient:
        return "Patient not found", 404

    # Get all medical record data
    conditions = database.get_patient_conditions(patient_id)
    medications = database.get_patient_medications(patient_id)
    allergies = database.get_patient_allergies(patient_id)
    goals = database.get_patient_goals(patient_id)
    messages = database.get_patient_messages(patient_id)

    # Calculate age if date of birth is available
    age = None
    if patient.get('date_of_birth'):
        from datetime import datetime
        try:
            dob = datetime.strptime(patient['date_of_birth'], '%Y-%m-%d')
            today = datetime.today()
            age_years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            age_months = (today.year - dob.year) * 12 + today.month - dob.month

            # If less than 36 months old, show years and months
            if age_months < 36:
                years = age_months // 12
                months = age_months % 12
                if years > 0:
                    age = f"{years}y {months}m"
                else:
                    age = f"{months}m"
            else:
                age = f"{age_years}y"
        except ValueError:
            pass

    return render_template('patient.html',
                         patient=patient,
                         age=age,
                         conditions=conditions,
                         medications=medications,
                         allergies=allergies,
                         goals=goals,
                         messages=messages)


@app.route('/messages/<int:patient_id>')
def get_messages(patient_id):
    """
    Get all messages for a patient.

    Args:
        patient_id: The patient's ID

    Returns:
        JSON array of messages
    """
    messages = database.get_patient_messages(patient_id)
    return jsonify(messages)


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    print('Client connected')


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    print('Client disconnected')


@socketio.on('join')
def handle_join(data):
    """Join a patient's chat room."""
    patient_id = data.get('patient_id')
    if patient_id:
        join_room(f'patient_{patient_id}')
        print(f'Client joined room for patient {patient_id}')


@socketio.on('request_greeting')
def handle_request_greeting(data):
    """Generate and send initial greeting for new patient."""
    patient_id = data.get('patient_id')
    if not patient_id:
        return

    # Check if messages already exist
    messages = database.get_patient_messages(patient_id)
    if messages:
        return  # Already has messages, no greeting needed

    # Generate greeting
    greeting = intake_parser.generate_greeting()

    # Save greeting message
    database.add_message(patient_id, 'agent', greeting)

    # Emit greeting to room
    emit('new_message', {
        'participant': 'agent',
        'content': greeting
    }, room=f'patient_{patient_id}')


@socketio.on('send_message')
def handle_send_message(data):
    """
    Handle incoming message from patient and generate agent response.

    Args:
        data: Dictionary with 'patient_id' and 'content'
    """
    patient_id = data.get('patient_id')
    content = data.get('content', '').strip()

    if not patient_id or not content:
        return

    # Save patient message
    database.add_message(patient_id, 'patient', content)

    # Emit patient message to room
    emit('new_message', {
        'participant': 'patient',
        'content': content
    }, room=f'patient_{patient_id}')

    # Get conversation history
    messages = database.get_patient_messages(patient_id)

    # Extract structured data from conversation
    extracted_data = intake_parser.extract_intake_data(messages)

    # Update patient demographics if provided
    if extracted_data.get('patient_updates'):
        database.update_patient(patient_id, **extracted_data['patient_updates'])

    # Add conditions
    for condition in extracted_data.get('conditions', []):
        database.add_condition(
            patient_id=patient_id,
            name=condition['name'],
            status=condition.get('status'),
            comment=condition.get('comment')
        )

    # Add medications
    for medication in extracted_data.get('medications', []):
        database.add_medication(
            patient_id=patient_id,
            name=medication['name'],
            dose=medication.get('dose'),
            form=medication.get('form'),
            sig=medication.get('sig'),
            indications=medication.get('indications')
        )

    # Add allergies
    for allergy in extracted_data.get('allergies', []):
        database.add_allergy(
            patient_id=patient_id,
            name=allergy['name'],
            comment=allergy.get('comment')
        )

    # Add goals
    for goal in extracted_data.get('goals', []):
        database.add_goal(
            patient_id=patient_id,
            name=goal['name'],
            comment=goal.get('comment')
        )

    # If any data was extracted, emit update to refresh medical record
    if any([
        extracted_data.get('patient_updates'),
        extracted_data.get('conditions'),
        extracted_data.get('medications'),
        extracted_data.get('allergies'),
        extracted_data.get('goals')
    ]):
        # Get updated medical record data
        patient = database.get_patient(patient_id)
        conditions = database.get_patient_conditions(patient_id)
        medications = database.get_patient_medications(patient_id)
        allergies = database.get_patient_allergies(patient_id)
        goals = database.get_patient_goals(patient_id)

        # Emit medical record update
        emit('medical_record_update', {
            'patient': patient,
            'conditions': conditions,
            'medications': medications,
            'allergies': allergies,
            'goals': goals
        }, room=f'patient_{patient_id}')

    # Generate conversational response
    agent_response = intake_parser.generate_response(messages)

    # Save agent message
    database.add_message(patient_id, 'agent', agent_response)

    # Emit agent message to room
    emit('new_message', {
        'participant': 'agent',
        'content': agent_response
    }, room=f'patient_{patient_id}')


if __name__ == '__main__':
    # Initialize database if it doesn't exist
    if not os.path.exists(database.DATABASE_PATH):
        database.init_db()

    socketio.run(app, debug=True, port=5000)
