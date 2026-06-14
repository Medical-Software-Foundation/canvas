"""Shared constants for the Photon Health prescription integration."""

from __future__ import annotations

# --- Custom command field -------------------------------------------------

# Key used both for the form field and for the stored CommandMetadata record.
PHOTON_FIELD_KEY = "send_via_photon"
PHOTON_FIELD_LABEL = "Send via Photon"
# Single-option SELECT: choosing the option marks the prescription for Photon
# transmission. An empty/unset value is the implicit "no" (use Canvas native).
PHOTON_FIELD_OPTION = "Send via Photon"
PHOTON_FIELD_OPTIONS = [PHOTON_FIELD_OPTION]
PHOTON_FIELD_TRUE_VALUE = PHOTON_FIELD_OPTION

# --- Command schema keys --------------------------------------------------
# Sourced from canvas_sdk.commands.commands.*.Meta.key.

PRESCRIBE_SCHEMA_KEY = "prescribe"
REFILL_SCHEMA_KEY = "refill"
ADJUST_PRESCRIPTION_SCHEMA_KEY = "adjustPrescription"

# Commands that receive the "Send via Photon" field.
PHOTON_COMMAND_SCHEMA_KEYS = frozenset(
    {PRESCRIBE_SCHEMA_KEY, REFILL_SCHEMA_KEY, ADJUST_PRESCRIPTION_SCHEMA_KEY}
)

# --- Action filtering -----------------------------------------------------
# When "Send via Photon" is set we remove the Canvas transmission actions so
# the prescription is signed (which triggers the Photon push) but never sent or
# sign-and-sent through Canvas's own pharmacy channel. `sign_action`,
# `print_action`/`print`, and `review` are intentionally retained.
ACTIONS_TO_REMOVE_WHEN_PHOTON = frozenset({"send_action", "sign_send_action"})

# --- Patient external identifier ------------------------------------------
# The Photon patient id is persisted on the Canvas patient under this system so
# subsequent sends reuse the same Photon patient instead of re-creating one.
PHOTON_PATIENT_ID_SYSTEM = "https://photon.health/patient"

# --- Failure task ---------------------------------------------------------
PHOTON_TASK_LABEL = "photon"
