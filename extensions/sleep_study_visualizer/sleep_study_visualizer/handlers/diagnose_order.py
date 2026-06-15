from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.command import Command, CommandMetadata
from canvas_sdk.v1.data.team import Team
from logger import log


def _build_order_task(
    patient: Patient,
    command: Command,
    note_uuid: str,
    team_id: str,
) -> AddTask:
    """Construct the HST order task.

    This function is intentionally isolated so that a future iteration can call
    an HST vendor API here instead of (or in addition to) creating the task.
    """
    diagnose_data = command.data or {}
    diagnose_coding = diagnose_data.get("diagnose", {})
    icd10_text = diagnose_coding.get("text", "")
    icd10_code = ""
    extra = diagnose_coding.get("extra") or {}
    codings = extra.get("coding", [])
    if codings:
        icd10_code = codings[0].get("code", "")

    icd10_label = f"{icd10_code} — {icd10_text}" if icd10_code else icd10_text

    title = (
        f"Order HST: {patient.first_name} {patient.last_name} "
        f"(MRN: {patient.mrn}) — {icd10_label}".strip(" —")
    )

    return AddTask(
        team_id=team_id,
        patient_id=str(patient.id),
        title=title,
        status=TaskStatus.OPEN,
        labels=["sleep-study-order"],
    )


class DiagnoseOrderHandler(BaseHandler):
    """Creates a Sleep Studies team task when the provider orders an HST.

    Responds to DIAGNOSE_COMMAND__POST_COMMIT.

    Fail-closed behaviour:
    - If the custom field is absent or set to 'No' → do nothing.
    - If SLEEP_STUDIES_TEAM_NAME secret is missing or the team is not found
      → log a warning and return no effects (no silent data loss).
    """

    RESPONDS_TO = EventType.Name(EventType.DIAGNOSE_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        command_uuid = self.event.target.id

        # Read the custom field stored by DiagnoseAdditionalFieldsHandler.
        try:
            meta = CommandMetadata.objects.get(
                command__id=command_uuid,
                key="sleep_study_order",
            )
        except CommandMetadata.DoesNotExist:
            return []

        if meta.value != "Yes":
            return []

        # --- Fail closed on missing variable ---
        team_id = self.secrets.get("SLEEP_STUDIES_TEAM_ID", "").strip()
        if not team_id:
            log.warning(
                "[DiagnoseOrderHandler] SLEEP_STUDIES_TEAM_ID is not configured. "
                "Skipping HST order task creation."
            )
            return []

        # --- Resolve team by FHIR Group ID (more reliable than name lookup) ---
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            log.warning(
                "[DiagnoseOrderHandler] Team with id '%s' not found. "
                "Skipping HST order task creation.",
                team_id,
            )
            return []

        # --- Resolve patient ---
        patient_id = self.event.context.get("patient", {}).get("id")
        if not patient_id:
            log.warning(
                "[DiagnoseOrderHandler] No patient ID in event context — "
                "cannot create order task."
            )
            return []

        patient = Patient.objects.get(id=patient_id)

        # --- Resolve command ---
        command = Command.objects.get(id=command_uuid)

        task = _build_order_task(
            patient=patient,
            command=command,
            note_uuid=self.event.context.get("note", {}).get("uuid", ""),
            team_id=str(team.id),
        )
        return [task.apply()]
