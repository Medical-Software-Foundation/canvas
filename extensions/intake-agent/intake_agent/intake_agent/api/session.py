"""
Session management for intake chat conversations.

Uses Canvas SDK cache to store conversation state. The session schema is defined
in schemas/intake_session.json and validated on creation and updates.
"""

import json
import re
import uuid
from datetime import datetime, timezone

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.templates import render_to_string
from logger import log


def validate_session_data(session_data: dict) -> None:
    """
    Validate session data structure.

    This validates the session data against the expected structure defined in
    schemas/intake_session.json. Since jsonschema is not available in the Canvas
    SDK sandbox, this implements custom validation logic.

    Args:
        session_data: Session data dictionary to validate

    Raises:
        ValueError: If session data doesn't match expected structure
    """
    # Check required top-level fields
    required_fields = ["session_id", "created_at", "updated_at", "messages", "collected_data", "status"]
    for field in required_fields:
        if field not in session_data:
            raise ValueError(f"Missing required field: {field}")

    # Validate session_id format (32-character hex)
    session_id = session_data["session_id"]
    if not isinstance(session_id, str) or not re.match(r"^[a-f0-9]{32}$", session_id):
        raise ValueError(f"Invalid session_id format: {session_id}")

    # Validate timestamps are strings (ISO 8601 format)
    for timestamp_field in ["created_at", "updated_at"]:
        if not isinstance(session_data[timestamp_field], str):
            raise ValueError(f"{timestamp_field} must be a string")

    # Validate messages array
    messages = session_data["messages"]
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError("Each message must be a dict")
        if "role" not in msg or "content" not in msg or "timestamp" not in msg:
            raise ValueError("Message missing required fields (role, content, timestamp)")
        if msg["role"] not in ["agent", "user"]:
            raise ValueError(f"Invalid message role: {msg['role']}")
        if not isinstance(msg["content"], str):
            raise ValueError("Message content must be a string")
        if not isinstance(msg["timestamp"], str):
            raise ValueError("Message timestamp must be a string")

    # Validate collected_data
    collected_data = session_data["collected_data"]
    if not isinstance(collected_data, dict):
        raise ValueError("collected_data must be a dict")

    required_data_fields = ["first_name", "last_name", "email", "phone", "date_of_birth", "reason_for_visit"]
    for field in required_data_fields:
        if field not in collected_data:
            raise ValueError(f"collected_data missing required field: {field}")

        value = collected_data[field]
        # Values can be None or strings
        if value is not None and not isinstance(value, str):
            raise ValueError(f"collected_data.{field} must be None or string")

        # Validate date_of_birth format if present
        if field == "date_of_birth" and value is not None:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                raise ValueError(f"Invalid date_of_birth format: {value} (expected YYYY-MM-DD)")

    # Validate status
    status = session_data["status"]
    if status not in ["active", "completed", "abandoned"]:
        raise ValueError(f"Invalid status: {status}")

    # Validate patient_record_status if present (optional field)
    # Status codes: 1=not_started, 2=pending, 3=complete
    if "patient_record_status" in session_data:
        patient_record_status = session_data["patient_record_status"]
        if patient_record_status is not None and not isinstance(patient_record_status, int):
            raise ValueError("patient_record_status must be None or int")
        if patient_record_status is not None and patient_record_status not in [1, 2, 3]:
            raise ValueError("patient_record_status must be 1 (not_started), 2 (pending), or 3 (complete)")

    # Validate phone_verification_code if present (optional field)
    if "phone_verification_code" in session_data:
        verification_code = session_data["phone_verification_code"]
        if verification_code is not None:
            if not isinstance(verification_code, str):
                raise ValueError("phone_verification_code must be None or string")
            if not re.match(r"^\d{6}$", verification_code):
                raise ValueError("phone_verification_code must be a 6-digit string")

    # Validate phone_verified if present (optional field)
    if "phone_verified" in session_data:
        phone_verified = session_data["phone_verified"]
        if not isinstance(phone_verified, bool):
            raise ValueError("phone_verified must be a boolean")


def generate_session_id() -> str:
    """
    Generate a cryptographically secure random session ID.

    Returns:
        A 32-character hexadecimal string
    """
    return uuid.uuid4().hex


def create_session() -> dict:
    """
    Create a new chat session.

    Returns:
        Dictionary containing the session data

    Raises:
        jsonschema.ValidationError: If session data doesn't match schema
    """
    now = datetime.now(timezone.utc).isoformat()
    session_id = generate_session_id()

    session_data = {
        "session_id": session_id,
        "created_at": now,
        "updated_at": now,
        "messages": [],
        "collected_data": {
            "first_name": None,
            "last_name": None,
            "email": None,
            "phone": None,
            "date_of_birth": None,
            "reason_for_visit": None
        },
        "status": "active",
        "phone_verification_code": None,
        "phone_verified": False,
        "patient_record_status": None
    }

    # Validate session data against schema
    validate_session_data(session_data)

    cache = get_cache()
    cache_key = f"intake_session:{session_id}"

    # Store for 1 hour (3600 seconds)
    cache.set(cache_key, session_data, timeout_seconds=3600)

    log.info(f"Created new session: {session_id}")
    return session_data


def get_session(session_id: str) -> dict | None:
    """
    Retrieve a session from cache.

    Args:
        session_id: The session identifier

    Returns:
        Session data dictionary or None if not found
    """
    cache = get_cache()
    cache_key = f"intake_session:{session_id}"

    session_data = cache.get(cache_key)

    if session_data:
        log.info(f"Retrieved session: {session_id}")
    else:
        log.warning(f"Session not found: {session_id}")

    return session_data


def update_session(session_id: str, session_data: dict) -> None:
    """
    Update a session in cache.

    Args:
        session_id: The session identifier
        session_data: Updated session data dictionary

    Raises:
        jsonschema.ValidationError: If session data doesn't match schema
    """
    cache = get_cache()
    cache_key = f"intake_session:{session_id}"

    # Update timestamp
    session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Validate session data against schema before storing
    validate_session_data(session_data)

    # Store for 1 hour (3600 seconds)
    cache.set(cache_key, session_data, timeout_seconds=3600)

    log.info(f"Updated session: {session_id}")


def add_message(session_id: str, role: str, content: str) -> dict | None:
    """
    Add a message to the session conversation.

    Args:
        session_id: The session identifier
        role: Either "agent" or "user"
        content: The message content

    Returns:
        Updated session data or None if session not found
    """
    session_data = get_session(session_id)

    if not session_data:
        return None

    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    session_data["messages"].append(message)
    update_session(session_id, session_data)

    log.info(f"Added {role} message to session {session_id}")
    return session_data


def update_collected_data(session_id: str, field: str, value: str) -> dict | None:
    """
    Update a field in the collected data.

    Args:
        session_id: The session identifier
        field: Field name (first_name, last_name, email, phone, date_of_birth, reason_for_visit)
        value: The value to store

    Returns:
        Updated session data or None if session not found
    """
    session_data = get_session(session_id)

    if not session_data:
        return None

    if field in session_data["collected_data"]:
        session_data["collected_data"][field] = value
        update_session(session_id, session_data)
        log.info(f"Updated {field} in session {session_id}")
    else:
        log.warning(f"Invalid field {field} for session {session_id}")

    return session_data


def complete_session(session_id: str) -> dict | None:
    """
    Mark a session as completed.

    Args:
        session_id: The session identifier

    Returns:
        Updated session data or None if session not found
    """
    session_data = get_session(session_id)

    if not session_data:
        return None

    session_data["status"] = "completed"
    update_session(session_id, session_data)

    log.info(f"Completed session: {session_id}")
    return session_data
