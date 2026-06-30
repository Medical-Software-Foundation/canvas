"""Protocols for ICD-10 coding integrity during assess and update-diagnosis commands."""

from canvas_sdk.commands.commands.assess import AssessCommand
from canvas_sdk.commands.constants import CodeSystems
from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.condition import ConditionCoding
from logger import log


class AssessConditionValidation(BaseProtocol):
    """Block assess command commits when the target condition has no ICD-10 coding.

    Fires on ASSESS_COMMAND__POST_VALIDATION. If the condition field is absent
    (e.g. assess without a diagnosis), returns [] (no-op). Only blocks when the
    condition explicitly lacks an ICD-10 coding — conditions that already have
    one pass through unchecked.
    """

    RESPONDS_TO = EventType.Name(EventType.ASSESS_COMMAND__POST_VALIDATION)

    def compute(self) -> list[Effect]:
        """Validate that the assessed condition has an ICD-10 coding."""
        log.info("[ICD-10 Coding] Running assess condition validation")

        condition_field = self.event.context["fields"].get("condition")
        if not condition_field:
            return []

        # The staged-command stores the condition's *dbid* in the value field
        # (confirmed by _has_pending_update_diagnosis_command which filters on
        # data__condition__value=condition.dbid).
        condition_dbid = condition_field.get("value")
        if not condition_dbid:
            return []

        log.info(
            f"[ICD-10 Coding] Validating assess for condition dbid: {condition_dbid}"
        )

        # Filter by condition_id (DB pk / dbid) — not condition__id (external key).
        # Also exclude entered_in_error codings for cleanliness.
        has_icd10 = ConditionCoding.objects.filter(
            condition_id=condition_dbid,
            system=CodeSystems.ICD10,
            condition__entered_in_error__isnull=True,
        ).exists()

        if has_icd10:
            return []

        effect = CommandValidationErrorEffect()
        effect.add_error(
            "Condition must have an ICD-10 coding before it can be assessed"
        )
        return [effect.apply()]


class UpdateAssessAfterChangeDiagnosis(BaseProtocol):
    """Re-point open staged assess commands after a diagnosis code change.

    When UpdateDiagnosis is committed (changing a condition's primary coding),
    any staged assess commands referencing the old condition dbid must be
    re-pointed to the new condition. This prevents stale references from
    blocking clinicians.
    """

    RESPONDS_TO = EventType.Name(EventType.UPDATE_DIAGNOSIS_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        """Re-point open assess commands to the new condition."""
        log.info("[ICD-10 Coding] Running UpdateAssessAfterChangeDiagnosis protocol")

        old_condition_id = self.event.context["fields"]["condition"].get("value")
        new_condition_icd_code = self.event.context["fields"]["new_condition"].get(
            "value"
        )
        patient_id: str = self.event.context["patient"]["id"]

        # Look up the new condition via ConditionCoding (exclude entered_in_error).
        new_coding = (
            ConditionCoding.objects.filter(
                condition__patient__id=patient_id,
                code=new_condition_icd_code,
                system=CodeSystems.ICD10,
                condition__entered_in_error__isnull=True,
            )
            .order_by("-dbid")
            .first()
        )

        # Guard: if no matching coding found, do nothing rather than crashing.
        if new_coding is None:
            log.warning(
                f"[ICD-10 Coding] No ConditionCoding found for code {new_condition_icd_code} "
                f"on patient {patient_id}; skipping assess re-point"
            )
            return []

        new_condition_id = new_coding.condition.id
        log.info(f"[ICD-10 Coding] New condition id: {new_condition_id}")

        open_assess_commands = Command.objects.filter(
            patient__id=patient_id,
            schema_key="assess",
            data__condition__value=old_condition_id,
            state="staged",
        )

        effects: list[Effect] = []
        for assess_command in open_assess_commands:
            effects.append(
                AssessCommand(
                    command_uuid=str(assess_command.id),
                    condition_id=str(new_condition_id),
                ).edit()
            )

        log.info(f"[ICD-10 Coding] Re-pointed {len(effects)} assess command(s)")
        return effects
