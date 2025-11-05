"""
Session management for intake chat conversations.

Uses Canvas SDK cache to store conversation state with the following JSON schema:
{
    "session_id": str,
    "created_at": str (ISO 8601),
    "updated_at": str (ISO 8601),
    "messages": [
        {
            "role": "agent" | "user",
            "content": str,
            "timestamp": str (ISO 8601)
        }
    ],
    "collected_data": {
        "first_name": str | None,
        "last_name": str | None,
        "email": str | None,
        "phone": str | None
    },
    "status": "active" | "completed" | "abandoned"
}
"""

import uuid
from datetime import datetime, timezone

from canvas_sdk.caching.plugins import get_cache
from logger import log


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
            "phone": None
        },
        "status": "active"
    }

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
    """
    cache = get_cache()
    cache_key = f"intake_session:{session_id}"

    # Update timestamp
    session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

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
        field: Field name (first_name, last_name, email, phone)
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
