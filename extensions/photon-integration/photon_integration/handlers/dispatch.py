"""Pre-sync the patient to Photon when a 'Send via Photon' command is signed.

Photon prescriptions can only be written by an authenticated provider (a
user-access token), which the backend M2M token cannot do — so this handler does
NOT create the prescription. It only ensures the patient exists in Photon (M2M
`write:patient`) so they're ready when the provider sends from the note-footer
"Send to Photon" button or the Elements modal. The Photon patient id is persisted
on the Canvas patient for reuse.
"""

from __future__ import annotations

import uuid
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.patient import Patient
from logger import log

from photon_integration.client.photon_client import PhotonError
from photon_integration.constants import PHOTON_TASK_LABEL
from photon_integration.handlers.command_field import _photon_send_selected
from photon_integration.patient_sync import build_client, resolve_photon_patient

_PRESCRIBER_ID_KEYS = ("id", "key", "staff", "staff_id")


class PhotonDispatchHandler(BaseHandler):
    """On sign of a Photon-flagged command, pre-sync the patient to Photon."""

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
        if not patient_id:
            log.error("Photon pre-sync skipped: command %s has no patient", command_id)
            return []

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            log.error("Photon pre-sync skipped: patient %s not found", patient_id)
            return []

        try:
            _, ext_id_effect = resolve_photon_patient(patient, build_client(self.secrets))
        except PhotonError as exc:
            log.error("Photon patient pre-sync failed for %s: %s", patient_id, exc)
            return [self._failure_task(patient_id, context.get("fields") or {}, str(exc))]

        log.info("Photon patient pre-sync complete for command %s", command_id)
        return [ext_id_effect] if ext_id_effect is not None else []

    # -- failure -----------------------------------------------------------

    def _failure_task(
        self, patient_id: str, fields: dict[str, Any], reason: str
    ) -> Effect:
        staff_id = self._valid_uuid(self._prescriber_staff_id(fields))
        fallback_team = self._valid_uuid(self.secrets.get("PHOTON_FALLBACK_TEAM_ID"))
        return AddTask(
            patient_id=str(patient_id),
            assignee_id=staff_id,
            team_id=fallback_team,
            author_id=staff_id,
            title=f"Photon patient sync failed: {reason}",
            status=TaskStatus.OPEN,
            labels=[PHOTON_TASK_LABEL],
        ).apply()

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
