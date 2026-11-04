"""Persistence helpers for the connection: tokens and connection status.

Oura data itself is never persisted; see ``services/fetch.py``. Handlers use
these helpers rather than reaching into the ORM directly. Datetimes are UTC.

The plugin sandbox does not allow ``django.db.transaction``, so multi-step
operations are ordered to fail safe rather than wrapped atomically.
"""

import datetime as dt
from typing import Any

from oura_ring_viewer.models import OuraOAuthToken, OuraSyncState


def upsert_tokens(
    patient_id: str,
    *,
    access_token_ciphertext: str,
    refresh_token_ciphertext: str,
    expires_at: dt.datetime,
    scopes: str,
    now: dt.datetime,
    is_initial_connection: bool,
) -> None:
    """Insert or update the token row for the patient."""
    defaults: dict[str, Any] = {
        "access_token": access_token_ciphertext,
        "refresh_token": refresh_token_ciphertext,
        "expires_at": expires_at,
        "last_refresh_at": now,
    }
    if scopes:
        defaults["scopes"] = scopes
    if is_initial_connection:
        defaults["connected_at"] = now
    OuraOAuthToken.objects.update_or_create(patient_id=patient_id, defaults=defaults)


def get_tokens(patient_id: str) -> OuraOAuthToken | None:
    """Return the raw stored token row for the patient, or None."""
    return OuraOAuthToken.objects.filter(patient_id=patient_id).first()


def delete_all_for_patient(patient_id: str) -> None:
    """Disconnect: remove every plugin row for the patient.

    Tokens are deleted first, so a failure partway through still leaves the
    patient effectively disconnected: with no tokens, nothing can be fetched.
    """
    OuraOAuthToken.objects.filter(patient_id=patient_id).delete()
    OuraSyncState.objects.filter(patient_id=patient_id).delete()


def upsert_sync_state(patient_id: str, **fields: Any) -> OuraSyncState:
    """Update or create the status row, writing only the supplied fields."""
    state, _ = OuraSyncState.objects.update_or_create(patient_id=patient_id, defaults=fields)
    return state


def get_sync_state(patient_id: str) -> OuraSyncState | None:
    """Return the status row, or None if the patient never connected."""
    return OuraSyncState.objects.filter(patient_id=patient_id).first()
