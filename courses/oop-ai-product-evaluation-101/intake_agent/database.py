"""
Database initialization and helper functions for Rose Clinic Intake Agent.
"""

import sqlite3
from pathlib import Path
from typing import Optional


DATABASE_PATH = Path(__file__).parent / "intake_agent.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db_connection():
    """Create and return a database connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
    return conn


def init_db():
    """Initialize the database by executing the schema file."""
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()

    conn = get_db_connection()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print(f"Database initialized at {DATABASE_PATH}")


def create_patient(first_name: Optional[str] = None,
                  last_name: Optional[str] = None,
                  date_of_birth: Optional[str] = None,
                  sex: Optional[str] = None,
                  gender: Optional[str] = None,
                  current_health_concerns: Optional[str] = None) -> int:
    """
    Create a new patient record and return the patient ID.

    Args:
        first_name: Patient's first name
        last_name: Patient's last name
        date_of_birth: Date of birth in YYYY-MM-DD format
        sex: Biological sex
        gender: Gender identity
        current_health_concerns: Free text for patient's health concerns

    Returns:
        The ID of the newly created patient
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO patient (first_name, last_name, date_of_birth, sex, gender, current_health_concerns)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (first_name, last_name, date_of_birth, sex, gender, current_health_concerns))

    patient_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return patient_id


def get_patient(patient_id: int) -> Optional[dict]:
    """
    Retrieve a patient by ID.

    Args:
        patient_id: The patient's ID

    Returns:
        Dictionary with patient data, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM patient WHERE id = ?", (patient_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def get_all_patients():
    """
    Retrieve all patients.

    Returns:
        List of patient dictionaries
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM patient ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def update_patient(patient_id: int, **kwargs):
    """
    Update patient information.

    Args:
        patient_id: The patient's ID
        **kwargs: Fields to update (first_name, last_name, date_of_birth, sex, gender, current_health_concerns)
    """
    allowed_fields = ["first_name", "last_name", "date_of_birth", "sex", "gender", "current_health_concerns"]
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

    if not updates:
        return

    # If sex is updated but gender is not provided, default gender to sex
    if 'sex' in updates and 'gender' not in kwargs:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT gender FROM patient WHERE id = ?", (patient_id,))
        current = cursor.fetchone()
        conn.close()

        # Only set gender to sex if gender is currently null
        if current and not current['gender']:
            updates['gender'] = updates['sex']

    set_clause = ", ".join([f"{field} = ?" for field in updates.keys()])
    values = list(updates.values()) + [patient_id]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        UPDATE patient
        SET {set_clause}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, values)

    conn.commit()
    conn.close()


def get_patient_conditions(patient_id: int):
    """Get all conditions for a patient."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM condition WHERE patient_id = ? ORDER BY created_at", (patient_id,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_patient_medications(patient_id: int):
    """Get all medications for a patient."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM medication WHERE patient_id = ? ORDER BY created_at", (patient_id,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_patient_allergies(patient_id: int):
    """Get all allergies for a patient."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM allergy WHERE patient_id = ? ORDER BY created_at", (patient_id,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_patient_goals(patient_id: int):
    """Get all goals for a patient."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM goal WHERE patient_id = ? ORDER BY created_at", (patient_id,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_patient_messages(patient_id: int):
    """Get all messages for a patient in chronological order."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM message WHERE patient_id = ? ORDER BY created_at", (patient_id,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def add_message(patient_id: int, participant: str, content: str) -> int:
    """
    Add a message to the conversation.

    Args:
        patient_id: The patient's ID
        participant: Either 'patient' or 'agent'
        content: The message content

    Returns:
        The ID of the newly created message
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO message (patient_id, participant, content)
        VALUES (?, ?, ?)
    """, (patient_id, participant, content))

    message_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return message_id


def add_condition(patient_id: int, name: str, status: Optional[str] = None, comment: Optional[str] = None) -> int:
    """Add or update a condition in patient record."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if condition already exists for this patient
    cursor.execute("""
        SELECT id, status, comment FROM condition
        WHERE patient_id = ? AND LOWER(name) = LOWER(?)
    """, (patient_id, name))
    existing = cursor.fetchone()

    if existing:
        # Update existing condition with any new information
        updates = {}
        if status and not existing['status']:
            updates['status'] = status
        if comment and not existing['comment']:
            updates['comment'] = comment

        if updates:
            set_clause = ", ".join([f"{field} = ?" for field in updates.keys()])
            values = list(updates.values()) + [existing['id']]
            cursor.execute(f"""
                UPDATE condition
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, values)
            conn.commit()

        condition_id = existing['id']
        conn.close()
        return condition_id

    # Insert new condition
    cursor.execute("""
        INSERT INTO condition (patient_id, name, status, comment)
        VALUES (?, ?, ?, ?)
    """, (patient_id, name, status, comment))

    condition_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return condition_id


def add_medication(patient_id: int, name: str, dose: Optional[str] = None,
                  form: Optional[str] = None, sig: Optional[str] = None,
                  indications: Optional[str] = None) -> int:
    """Add or update a medication in patient record."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if medication already exists for this patient (match on name only)
    cursor.execute("""
        SELECT id, dose, form, sig, indications FROM medication
        WHERE patient_id = ? AND LOWER(name) = LOWER(?)
    """, (patient_id, name))
    existing = cursor.fetchone()

    if existing:
        # Update existing medication with any new information
        updates = {}
        if dose and not existing['dose']:
            updates['dose'] = dose
        if form and not existing['form']:
            updates['form'] = form
        if sig and not existing['sig']:
            updates['sig'] = sig
        if indications and not existing['indications']:
            updates['indications'] = indications

        if updates:
            set_clause = ", ".join([f"{field} = ?" for field in updates.keys()])
            values = list(updates.values()) + [existing['id']]
            cursor.execute(f"""
                UPDATE medication
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, values)
            conn.commit()

        medication_id = existing['id']
        conn.close()
        return medication_id

    # Insert new medication
    cursor.execute("""
        INSERT INTO medication (patient_id, name, dose, form, sig, indications)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (patient_id, name, dose, form, sig, indications))

    medication_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return medication_id


def add_allergy(patient_id: int, name: str, comment: Optional[str] = None) -> int:
    """Add or update an allergy in patient record."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if allergy already exists for this patient
    cursor.execute("""
        SELECT id, comment FROM allergy
        WHERE patient_id = ? AND LOWER(name) = LOWER(?)
    """, (patient_id, name))
    existing = cursor.fetchone()

    if existing:
        # Update existing allergy with any new information
        if comment and not existing['comment']:
            cursor.execute("""
                UPDATE allergy
                SET comment = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (comment, existing['id']))
            conn.commit()

        allergy_id = existing['id']
        conn.close()
        return allergy_id

    # Insert new allergy
    cursor.execute("""
        INSERT INTO allergy (patient_id, name, comment)
        VALUES (?, ?, ?)
    """, (patient_id, name, comment))

    allergy_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return allergy_id


def add_goal(patient_id: int, name: str, comment: Optional[str] = None) -> int:
    """Add or update a goal in patient record."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if goal already exists for this patient
    cursor.execute("""
        SELECT id, comment FROM goal
        WHERE patient_id = ? AND LOWER(name) = LOWER(?)
    """, (patient_id, name))
    existing = cursor.fetchone()

    if existing:
        # Update existing goal with any new information
        if comment and not existing['comment']:
            cursor.execute("""
                UPDATE goal
                SET comment = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (comment, existing['id']))
            conn.commit()

        goal_id = existing['id']
        conn.close()
        return goal_id

    # Insert new goal
    cursor.execute("""
        INSERT INTO goal (patient_id, name, comment)
        VALUES (?, ?, ?)
    """, (patient_id, name, comment))

    goal_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return goal_id


def get_patient_completeness(patient_id: int) -> dict:
    """
    Calculate completeness status for each major data category.

    Args:
        patient_id: The patient's ID

    Returns:
        Dictionary with completeness status for each category:
        - demographics: bool (has name, DOB, sex/gender)
        - concerns: bool (has current health concerns)
        - conditions: bool (has at least one condition)
        - medications: bool (has at least one medication)
        - allergies: bool (has at least one allergy)
        - goals: bool (has at least one goal)
    """
    patient = get_patient(patient_id)
    if not patient:
        return {
            'demographics': False,
            'concerns': False,
            'conditions': False,
            'medications': False,
            'allergies': False,
            'goals': False
        }

    # Check demographics (name and DOB and sex/gender)
    demographics_complete = (
        patient.get('first_name') and
        patient.get('last_name') and
        patient.get('date_of_birth') and
        (patient.get('sex') or patient.get('gender'))
    )

    # Check health concerns
    concerns_complete = bool(patient.get('current_health_concerns'))

    # Check other categories
    conditions = get_patient_conditions(patient_id)
    medications = get_patient_medications(patient_id)
    allergies = get_patient_allergies(patient_id)
    goals = get_patient_goals(patient_id)

    return {
        'demographics': demographics_complete,
        'concerns': concerns_complete,
        'conditions': len(conditions) > 0,
        'medications': len(medications) > 0,
        'allergies': len(allergies) > 0,
        'goals': len(goals) > 0
    }


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
