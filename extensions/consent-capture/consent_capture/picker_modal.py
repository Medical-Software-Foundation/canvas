"""Build the patient-facing consent picker modal.

Opened by ``ConsentButton``, the "Consents" chart-header button that is always
shown for a patient (red when a required consent is due, gray otherwise).

Kept out of ``service.py`` (which stays data-only) because this layer renders a
template and builds an Effect.
"""

import json

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient

from logger import log

from consent_capture.constants import METHOD_OPTIONS, NO_STATEMENT_NOTE
from consent_capture.service import (
    consent_records,
    is_consent_admin,
    picker_items,
    practice_settings,
)

# The Consent Settings page URL (served by ConsentAdminApi); opened from the wrench.
SETTINGS_URL = "/plugin-io/api/consent_capture/admin/settings"


def _patient_name_dob(patient_id):
    """Return ``(name, dob_iso)`` for the patient, or empty strings."""
    if not patient_id:
        return "", ""
    row = (
        Patient.objects.filter(id=patient_id)
        .values_list("first_name", "last_name", "suffix", "birth_date")
        .first()
    )
    if not row:
        return "", ""
    # Includes the suffix: the signing screen's name check compares it.
    name = " ".join(n for n in (row[0], row[1], row[2]) if n)
    dob = row[3].isoformat() if row[3] else ""
    return name, dob


def build_picker_modal(patient_id, staff_id, secrets):
    """Render the consent picker and return an (un-applied) ``LaunchModalEffect``.

    The caller applies it (the button returns ``[effect.apply()]``; the app returns
    ``effect.apply()``). ``is_admin`` gates the in-modal Settings gear for the
    logged-in staff; ``secrets`` supplies the ``CONSENT_ADMIN_USERS`` allow-list.
    """
    items = picker_items(patient_id)
    records = consent_records(patient_id)
    patient_name, patient_dob = _patient_name_dob(patient_id)
    admin_users = (secrets or {}).get("CONSENT_ADMIN_USERS", "")
    is_admin = is_consent_admin(staff_id, admin_users)

    log.info(
        "consent picker opened for patient %s by staff %s (%d consents, %d records)"
        % (patient_id, staff_id, len(items), len(records))
    )

    html = render_to_string(
        "templates/picker.html",
        {
            "patient_id": patient_id,
            "patient_name": patient_name,
            "patient_dob": patient_dob,
            "consents_json": json.dumps(items),
            "records_json": json.dumps(records),
            "method_options_json": json.dumps(list(METHOD_OPTIONS)),
            "practice_json": json.dumps(practice_settings()),
            "no_statement_note": NO_STATEMENT_NOTE,
            "is_admin": is_admin,
            "settings_url": SETTINGS_URL,
        },
    )
    return LaunchModalEffect(
        target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        content=html,
        title="Consents",
    )
