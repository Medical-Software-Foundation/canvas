"""Shared Photon patient-sync helpers.

Used by both the backend dispatch handler and the prescribe-modal API so the
Photon patient (and its persisted external id) is resolved identically.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import CreatePatientExternalIdentifier
from canvas_sdk.v1.data.common import ContactPointSystem
from canvas_sdk.v1.data.patient import Patient

from photon_integration.client.photon_client import PhotonClient, PhotonError
from photon_integration.constants import PHOTON_PATIENT_ID_SYSTEM

_SEX_MAP = {"F": "FEMALE", "M": "MALE"}


def build_client(secrets: Any) -> PhotonClient:
    """Construct a PhotonClient from a handler's ``self.secrets`` mapping."""
    return PhotonClient(
        client_id=secrets.get("PHOTON_CLIENT_ID", ""),
        client_secret=secrets.get("PHOTON_CLIENT_SECRET", ""),
        env=(secrets.get("PHOTON_ENV") or "sandbox").strip().lower(),
    )


def contact_value(patient: Patient, system: ContactPointSystem) -> str | None:
    contact = patient.telecom.filter(system=system).order_by("rank").first()
    return str(contact.value) if contact and contact.value else None


def _e164_phone(raw: str | None) -> str | None:
    """Normalize a Canvas phone to E.164 (``+1XXXXXXXXXX``) for Photon.

    Photon's ``createPatient`` rejects formatted numbers like ``(415) 555-1234``.
    Handles the common US shapes and already-prefixed international numbers;
    returns ``None`` when it can't form a plausible E.164 value.
    """
    if not raw:
        return None
    raw = raw.strip()
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if raw.startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:  # US local
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):  # US with country code
        return f"+{digits}"
    return None


def build_address(patient: Patient) -> dict[str, Any] | None:
    address = patient.addresses.first()
    if not address:
        return None
    return {
        "street1": address.line1,
        "street2": address.line2 or None,
        "city": address.city,
        "state": address.state_code,
        "postalCode": address.postal_code,
        "country": address.country or "US",
    }


def build_patient_input(patient: Patient) -> dict[str, Any]:
    if not patient.first_name or not patient.last_name:
        raise PhotonError(f"Patient {patient.id} is missing a name for Photon sync")
    if not patient.birth_date:
        raise PhotonError(f"Patient {patient.id} is missing a date of birth")

    raw_phone = contact_value(patient, ContactPointSystem.PHONE)
    phone = _e164_phone(raw_phone)
    if not phone:
        if raw_phone:
            raise PhotonError(
                f"Patient {patient.id} phone {raw_phone!r} can't be formatted for "
                "Photon (E.164, e.g. +14155551234 — check the patient's phone)"
            )
        raise PhotonError(f"Patient {patient.id} has no phone number for Photon")

    return {
        "externalId": str(patient.id),
        "name": {"first": patient.first_name, "last": patient.last_name},
        "dateOfBirth": patient.birth_date.isoformat(),
        "sex": _SEX_MAP.get((patient.sex_at_birth or "").upper(), "UNKNOWN"),
        "phone": phone,
        "email": contact_value(patient, ContactPointSystem.EMAIL),
        "gender": None,
        "address": build_address(patient),
    }


def resolve_photon_patient(
    patient: Patient, client: PhotonClient
) -> tuple[str, Effect | None]:
    """Return (photon_patient_id, optional external-id effect to persist).

    Reuses the Photon patient id stored on the Canvas patient; otherwise creates
    the patient in Photon and returns a CreatePatientExternalIdentifier effect so
    the mapping is persisted for next time.
    """
    stored = patient.external_identifiers.filter(system=PHOTON_PATIENT_ID_SYSTEM).first()
    if stored and stored.value:
        return str(stored.value), None

    photon_patient_id = client.create_patient(build_patient_input(patient))
    persist = CreatePatientExternalIdentifier(
        patient_id=str(patient.id),
        system=PHOTON_PATIENT_ID_SYSTEM,
        value=photon_patient_id,
    ).create()
    return photon_patient_id, persist
