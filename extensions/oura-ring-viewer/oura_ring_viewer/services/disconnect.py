"""Stopping sharing, from either the chart or the patient portal."""

import datetime as dt

from oura_ring_viewer.services.config import (
    FETCH_SECRETS,
    build_client,
    config_problems,
)
from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.oauth import revoke_at_oura
from oura_ring_viewer.services.storage import delete_all_for_patient


def stop_sharing(patient_id: str, secrets: dict[str, str] | None, now: dt.datetime) -> bool:
    """End access at Oura, then remove everything held for the patient.

    Returns whether Oura confirmed it ended access. The local rows are removed
    either way: with no tokens, this plugin can no longer read the patient's
    data, whatever Oura says.
    """
    revoked = False
    if secrets and not config_problems(secrets, FETCH_SECRETS):
        revoked = revoke_at_oura(patient_id, build_client(secrets), TokenCipher(), now=now)
    delete_all_for_patient(patient_id)
    return revoked
