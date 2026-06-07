"""Push signed 'Send via Photon' prescriptions to Photon Health.

On the POST_COMMIT (sign) event of a prescribe/refill/adjust command whose
'Send via Photon' field is set, this handler:

1. Resolves the patient in Photon (stored external id -> Photon lookup ->
   create), persisting Photon's patient id back onto the Canvas patient.
2. Looks up the medication as a Photon treatment.
3. Resolves the prescriber (test override or by external id).
4. Creates the prescription, then an order (so Photon routes to a pharmacy).

Any expected Photon failure surfaces as a Canvas Task assigned to the
prescriber; unexpected errors propagate to monitoring.
"""

from __future__ import annotations

import uuid
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import CreatePatientExternalIdentifier
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.common import ContactPointSystem
from canvas_sdk.v1.data.patient import Patient
from logger import log

from photon_integration.client.photon_client import PhotonClient, PhotonError
from photon_integration.constants import (
    PHOTON_PATIENT_ID_SYSTEM,
    PHOTON_TASK_LABEL,
)
from photon_integration.handlers.command_field import _photon_send_selected

_SEX_MAP = {"F": "FEMALE", "M": "MALE"}
_MEDICATION_NAME_KEYS = ("text", "label", "name", "description", "display")
_PRESCRIBER_ID_KEYS = ("id", "key", "staff", "staff_id")


class PhotonDispatchHandler(BaseHandler):
    """Send signed Photon-flagged prescriptions to Photon Health."""

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.REFILL_COMMAND__POST_COMMIT),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT),
    ]

    def compute(self) -> list[Effect]:
        command_id = self.event.target.id
        if not _photon_send_selected(command_id):
            return []

        context = self.event.context
        patient_id = (context.get("patient") or {}).get("id")
        fields = context.get("fields") or {}

        if not patient_id:
            # A committed prescription should always carry a patient; without
            # one we cannot sync or build a meaningful Task.
            log.error("Photon dispatch skipped: command %s has no patient", command_id)
            return []

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            log.error("Photon dispatch skipped: patient %s not found", patient_id)
            return []

        effects: list[Effect] = []
        try:
            client = self._build_client()

            photon_patient_id, ext_id_effect = self._resolve_patient(client, patient)
            if ext_id_effect is not None:
                # Persist the Photon id even if a later step fails, so retries
                # reuse the same Photon patient.
                effects.append(ext_id_effect)

            treatment_id = self._resolve_treatment(client, fields)

            prescription_id = client.create_prescription(
                self._prescription_input(
                    command_id=command_id,
                    photon_patient_id=photon_patient_id,
                    treatment_id=treatment_id,
                    fields=fields,
                )
            )

            order_address = self._address_input(patient)
            if order_address is None:
                raise PhotonError(f"Patient {patient.id} has no address for the order")

            client.create_order(
                patient_id=photon_patient_id,
                prescription_id=prescription_id,
                address=order_address,
                pharmacy_id=self._resolve_pharmacy(fields),
                external_id=str(command_id),
            )
            log.info("Photon send complete for command %s", command_id)
        except PhotonError as exc:
            log.error("Photon send failed for command %s: %s", command_id, exc)
            effects.append(self._failure_task(patient_id, fields, str(exc)))

        return effects

    # -- configuration -----------------------------------------------------

    def _build_client(self) -> PhotonClient:
        return PhotonClient(
            client_id=self.secrets.get("PHOTON_CLIENT_ID", ""),
            client_secret=self.secrets.get("PHOTON_CLIENT_SECRET", ""),
            env=(self.secrets.get("PHOTON_ENV") or "sandbox").strip().lower(),
        )

    # -- patient -----------------------------------------------------------

    def _resolve_patient(
        self, client: PhotonClient, patient: Patient
    ) -> tuple[str, Effect | None]:
        """Return (photon_patient_id, optional external-id effect to persist).

        Photon's `patients` query has no server-side externalId filter, so we
        rely on the Photon patient id we persist on the Canvas patient after the
        first sync. When it's absent we create the patient (passing externalId so
        the mapping is recorded on Photon's side too).
        """
        stored = patient.external_identifiers.filter(
            system=PHOTON_PATIENT_ID_SYSTEM
        ).first()
        if stored and stored.value:
            return str(stored.value), None

        photon_patient_id = client.create_patient(self._patient_input(patient))
        persist = CreatePatientExternalIdentifier(
            patient_id=str(patient.id),
            system=PHOTON_PATIENT_ID_SYSTEM,
            value=photon_patient_id,
        ).create()
        return photon_patient_id, persist

    def _patient_input(self, patient: Patient) -> dict[str, Any]:
        if not patient.first_name or not patient.last_name:
            raise PhotonError(f"Patient {patient.id} is missing a name for Photon sync")
        if not patient.birth_date:
            raise PhotonError(f"Patient {patient.id} is missing a date of birth")

        phone = self._contact_value(patient, ContactPointSystem.PHONE)
        if not phone:
            raise PhotonError(f"Patient {patient.id} has no phone number for Photon")

        patient_input: dict[str, Any] = {
            "externalId": str(patient.id),
            "name": {"first": patient.first_name, "last": patient.last_name},
            "dateOfBirth": patient.birth_date.isoformat(),
            "sex": _SEX_MAP.get((patient.sex_at_birth or "").upper(), "UNKNOWN"),
            "phone": phone,
            "email": self._contact_value(patient, ContactPointSystem.EMAIL),
            "gender": None,
            "address": self._address_input(patient),
        }
        return patient_input

    @staticmethod
    def _contact_value(patient: Patient, system: ContactPointSystem) -> str | None:
        contact = (
            patient.telecom.filter(system=system).order_by("rank").first()
        )
        return str(contact.value) if contact and contact.value else None

    @staticmethod
    def _address_input(patient: Patient) -> dict[str, Any] | None:
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

    # -- medication --------------------------------------------------------

    def _resolve_treatment(self, client: PhotonClient, fields: dict[str, Any]) -> str:
        term = self._medication_term(fields)
        if not term:
            raise PhotonError("Could not determine the medication name to send to Photon")
        treatment_id = client.find_treatment_id(term)
        if not treatment_id:
            raise PhotonError(f"No Photon treatment match for '{term}'")
        return treatment_id

    @staticmethod
    def _medication_term(fields: dict[str, Any]) -> str | None:
        # Adjust Prescription carries the new drug in change_medication_to.
        for source_key in ("change_medication_to", "prescribe"):
            source = fields.get(source_key)
            if isinstance(source, str) and source.strip():
                return source.strip()
            if isinstance(source, dict):
                for key in _MEDICATION_NAME_KEYS:
                    value = source.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return None

    # -- prescriber --------------------------------------------------------

    @staticmethod
    def _prescriber_staff_id(fields: dict[str, Any]) -> str | None:
        prescriber = fields.get("prescriber")
        if isinstance(prescriber, str) and prescriber.strip():
            return prescriber.strip()
        if isinstance(prescriber, dict):
            for key in _PRESCRIBER_ID_KEYS:
                value = prescriber.get(key)
                if value:
                    return str(value)
        return None

    # -- prescription / pharmacy -------------------------------------------

    def _prescription_input(
        self,
        command_id: str,
        photon_patient_id: str,
        treatment_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        sig = (fields.get("sig") or "").strip()
        if not sig:
            raise PhotonError("Prescription has no SIG/instructions to send to Photon")

        quantity = fields.get("quantity_to_dispense")
        if quantity is None:
            raise PhotonError("Prescription has no quantity to dispense")

        dispense_unit = self._dispense_unit(fields)
        if not dispense_unit:
            raise PhotonError("Prescription has no dispense unit to send to Photon")

        refills = int(fields.get("refills") or 0)
        substitutions = str(fields.get("substitutions") or "").lower()

        return {
            "externalId": str(command_id),
            "patientId": photon_patient_id,
            "treatmentId": treatment_id,
            # DAW = no substitution allowed.
            "dispenseAsWritten": "not" in substitutions,
            "dispenseQuantity": float(quantity),
            "dispenseUnit": dispense_unit,
            "refillsAllowed": refills,
            "daysSupply": fields.get("days_supply"),
            "instructions": sig,
            "notes": fields.get("note_to_pharmacist") or None,
            "effectiveDate": None,
        }

    @staticmethod
    def _dispense_unit(fields: dict[str, Any]) -> str | None:
        type_to_dispense = fields.get("type_to_dispense")
        if isinstance(type_to_dispense, str) and type_to_dispense.strip():
            return type_to_dispense.strip()
        if isinstance(type_to_dispense, dict):
            for key in ("description", "text", "label", "name"):
                value = type_to_dispense.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    @staticmethod
    def _resolve_pharmacy(fields: dict[str, Any]) -> str | None:
        """Return a Photon pharmacy id (phr_*) when present, else None.

        Canvas pharmacies are NCPDP-based, so this usually returns None and
        Photon routes to the patient's preferred pharmacy.
        """
        pharmacy = fields.get("pharmacy")
        if isinstance(pharmacy, dict):
            for value in pharmacy.values():
                if isinstance(value, str) and value.startswith("phr_"):
                    return value
        return None

    # -- failure -----------------------------------------------------------

    def _failure_task(
        self, patient_id: str, fields: dict[str, Any], reason: str
    ) -> Effect:
        medication = self._medication_term(fields) or "prescription"
        # AddTask assignee/author/team require Canvas Staff/Team UUIDs. The
        # command's prescriber is a CanvasUser id (usr_...), not a UUID, so only
        # assign when we actually have a valid UUID; otherwise leave it
        # unassigned (authored by CanvasBot) rather than failing the Task.
        staff_id = self._valid_uuid(self._prescriber_staff_id(fields))
        fallback_team = self._valid_uuid(self.secrets.get("PHOTON_FALLBACK_TEAM_ID"))
        return AddTask(
            patient_id=str(patient_id),
            assignee_id=staff_id,
            team_id=fallback_team,
            author_id=staff_id,
            title=f"Photon send failed for {medication}: {reason}",
            status=TaskStatus.OPEN,
            labels=[PHOTON_TASK_LABEL],
        ).apply()

    @staticmethod
    def _valid_uuid(value: Any) -> str | None:
        """Return the value as a string only if it is a valid UUID, else None."""
        if not value:
            return None
        try:
            uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            return None
        return str(value)
