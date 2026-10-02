"""Walks a patient graph and produces the sync bundle JSON.

Three modes (see ``build``):

* **provision** — Patient only, with a `provision_token` external identifier
  marker so the target can find the newly-created patient by token.
* **remap** — Notes + Commands + Tasks only, with each record's
  `patient_id` rewritten to the caller-supplied `target_patient_id`. Used
  for the second call in the two-call protocol after the target has
  provisioned a patient.
* **full** — everything (Patient, identifiers, Notes, Commands, Tasks).
  Mostly here for completeness; the two-call protocol uses the first two.

The walker is modeled on the patient-visit-summary plugin's
``NoteDataExtractor`` (canvas-msf/extensions/patient-visit-summary).
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient, PatientExternalIdentifier
from canvas_sdk.v1.data.task import Task

from patient_sync_source.services.anonymizer import Anonymizer


SCHEMA_VERSION = "1.0"

# system value used in PatientExternalIdentifier rows that mark a freshly-
# provisioned patient on target. Source generates a provision_token (UUID),
# target stores it as an external identifier on Patient.create(), and the
# caller polls target's GET /provisioned/<token> to resolve the new key.
PROVISION_SYSTEM = "patient-sync:provision-token"


class BundleWalker:
    """Builds the JSON bundle for one patient."""

    def __init__(
        self,
        patient: Patient,
        *,
        anonymizer: Anonymizer,
        source_instance: str,
        sync_id: str,
        exported_at: str,
    ) -> None:
        self.patient = patient
        self.anonymizer = anonymizer
        self.source_instance = source_instance
        self.sync_id = sync_id
        self.exported_at = exported_at

    # ---------- Modes ----------

    def build_provision(self, *, provision_token: str) -> dict[str, Any]:
        """Bundle for the provision step — Patient only, with a marker."""
        return self._envelope(
            entities={
                "Patient": [self._serialize_patient(provision_token=provision_token)],
            },
        )

    def build_remap(self, *, target_patient_id: str) -> dict[str, Any]:
        """Bundle for the sync step — Notes/Commands/Tasks with rewritten patient_id."""
        return self._envelope(
            entities={
                "Note": self._serialize_notes(target_patient_id=target_patient_id),
                "Command": self._serialize_commands(),
                "Task": self._serialize_tasks(target_patient_id=target_patient_id),
            },
        )

    def build_full(self) -> dict[str, Any]:
        """Everything in one bundle. Mostly here for completeness."""
        return self._envelope(
            entities={
                "Patient": [self._serialize_patient()],
                "PatientExternalIdentifier": self._serialize_patient_external_identifiers(),
                "Note": self._serialize_notes(),
                "Command": self._serialize_commands(),
                "Task": self._serialize_tasks(),
            },
        )

    def _envelope(self, *, entities: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "sync_id": self.sync_id,
            "source_instance": self.source_instance,
            "exported_at": self.exported_at,
            "entities": entities,
        }

    # ---------- Patient ----------

    def _serialize_patient(self, *, provision_token: str | None = None) -> dict[str, Any]:
        p = self.patient
        record: dict[str, Any] = {
            "id": p.id,
            "first_name": self.anonymizer.first_name(p.first_name),
            "middle_name": self.anonymizer.middle_name(p.middle_name),
            "last_name": self.anonymizer.last_name(p.last_name),
            "birth_date": self._iso_date(self.anonymizer.birth_date(p.birth_date)),
            "sex_at_birth": p.sex_at_birth,
            "nickname": "",
            "mrn": self.anonymizer.mrn(p.mrn),
            "social_security_number": self.anonymizer.ssn(p.social_security_number),
            "active": p.active,
            "deceased": p.deceased,
            "default_location_id": p.default_location_id,
            "default_provider_id": p.default_provider_id,
        }
        if provision_token is not None:
            record["external_identifiers"] = [
                {"system": PROVISION_SYSTEM, "value": provision_token},
            ]
        return record

    def _serialize_patient_external_identifiers(self) -> list[dict[str, Any]]:
        """External identifiers pass through verbatim — they're the integrating system's own data, not Canvas PHI."""
        return [
            {
                "id": str(eid.id),
                "patient_id": self.patient.id,
                "use": eid.use,
                "identifier_type": eid.identifier_type,
                "system": eid.system,
                "value": eid.value,
                "issued_date": self._iso_date(eid.issued_date),
                "expiration_date": self._iso_date(eid.expiration_date),
            }
            for eid in PatientExternalIdentifier.objects.filter(patient=self.patient).order_by("dbid")
        ]

    # ---------- Notes ----------

    def _serialize_notes(self, *, target_patient_id: str | None = None) -> list[dict[str, Any]]:
        # FK columns ending in `_id` hold the internal dbid, not the
        # externally-exposable UUID. Traverse `.note_type_version.id` etc.
        # to get the UUIDs the SDK / target dispatcher expects.
        notes = (
            Note.objects.filter(patient=self.patient)
            .select_related("note_type_version", "provider", "location")
            .order_by("dbid")
        )
        patient_id_for_target = target_patient_id or self.patient.id
        return [
            {
                "id": str(n.id),
                "patient_id": patient_id_for_target,
                "provider_id": n.provider.id if n.provider else None,
                "location_id": str(n.location.id) if n.location else None,
                "note_type_id": str(n.note_type_version.id) if n.note_type_version else None,
                "title": n.title,
                "datetime_of_service": self._iso_datetime(n.datetime_of_service),
                "place_of_service": n.place_of_service,
                # Clear note body content for v1 — the rendered content is
                # reconstructed on target by re-originating the individual
                # commands below anyway. A future v2 NLP-scrubber pass could
                # preserve anonymized free-text if a use case demands it.
                "body": {},
                "billing_note": "",
                "related_data": n.related_data,
            }
            for n in notes
        ]

    # ---------- Commands ----------

    def _serialize_commands(self) -> list[dict[str, Any]]:
        """One row per committed, not-entered-in-error command across all of the patient's notes.

        Commands don't carry a patient_id of their own in the bundle — they
        reference their parent Note's id, and the Note already carries the
        correctly-remapped patient_id.
        """
        rows: list[dict[str, Any]] = []
        commands = (
            Command.objects.filter(
                patient=self.patient,
                state="committed",
                entered_in_error__isnull=True,
            )
            .select_related("note")
            .order_by("note__dbid", "dbid")
        )
        for cmd in commands:
            rows.append({
                "id": str(cmd.id),
                "note_id": str(cmd.note.id),
                "schema_key": cmd.schema_key,
                "state": cmd.state,
                "data": self.anonymizer.clear_free_text_fields(cmd.data),
            })
        return rows

    # ---------- Tasks ----------

    def _serialize_tasks(self, *, target_patient_id: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        tasks = (
            Task.objects.filter(patient=self.patient)
            .select_related("creator", "assignee", "team")
            .order_by("dbid")
        )
        patient_id_for_target = target_patient_id or self.patient.id
        for task in tasks:
            rows.append({
                "id": str(task.id),
                "patient_id": patient_id_for_target,
                "creator_id": task.creator.id if task.creator else None,
                "assignee_id": task.assignee.id if task.assignee else None,
                "team_id": str(task.team.id) if task.team else None,
                "task_type": task.task_type,
                "tag": task.tag,
                # Title is free-text but may include PHI; clear for safety.
                "title": "",
                "due": self._iso_datetime(task.due),
                "due_event": task.due_event,
                "status": task.status,
                "priority": task.priority,
            })
        return rows

    # ---------- Helpers ----------

    @staticmethod
    def _iso_date(value: Any) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _iso_datetime(value: Any) -> str | None:
        return value.isoformat() if value is not None else None
