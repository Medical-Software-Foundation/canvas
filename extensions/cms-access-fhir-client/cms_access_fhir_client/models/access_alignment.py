from django.db.models import (
    CASCADE,
    DO_NOTHING,
    BooleanField,
    DateField,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
    TextField,
)

from canvas_sdk.v1.data import ModelExtension, Patient
from canvas_sdk.v1.data.base import CustomModel


class CustomPatient(Patient, ModelExtension):
    pass


class ACCESSAlignment(CustomModel):
    """One row per (patient, track) historical alignment with the CMS ACCESS model."""

    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="access_alignments",
    )
    alignment_id = TextField(default="")
    track = TextField(default="")
    tier = TextField(default="")
    status = TextField(default="")
    clinical_justification = TextField(default="")
    care_start_date = DateField(default=None)
    care_end_date = DateField(default=None)
    unalignment_reason = TextField(default="")
    last_eligibility_check_at = DateTimeField(default=None)
    submission_status_url = TextField(default="")
    submission_state = TextField(default="")
    submission_op = TextField(default="")
    submission_started_at = DateTimeField(default=None)
    last_poll_at = DateTimeField(default=None)
    poll_attempts = IntegerField(default=0)
    # Populated when a submission or pre-validation returns an error message
    # (e.g. OperationOutcome issue detail text or $align 400 detail).
    status_message = TextField(default="")
    # $report-data is a reporting operation, not an alignment-state transition (OM v0.9.11
    # p.77). Its result comes from a separate code system (ACCESSReportDataResultVS:
    # success / validation-error / duplicate / patient-not-aligned / reporting-period-closed
    # / incomplete-data / incorrect-track) and is tracked here so it never overwrites the
    # alignment lifecycle status / status_message.
    report_result = TextField(default="")
    report_result_at = DateTimeField(default=None)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["status"]),
            Index(fields=["submission_state"]),
            Index(fields=["-updated_at"]),
        ]

    # Track choices
    TRACK_ECKM = "eCKM"
    TRACK_CKM = "CKM"
    TRACK_MSK = "MSK"
    TRACK_BH = "BH"
    TRACK_CHOICES = [TRACK_ECKM, TRACK_CKM, TRACK_MSK, TRACK_BH]

    # Tier choices
    TIER_INITIAL = "initial"
    TIER_RENEWAL = "renewal"

    # Status choices
    STATUS_ELIGIBLE = "eligible"
    STATUS_INELIGIBLE = "ineligible"
    STATUS_ALREADY_ALIGNED = "already-aligned"
    STATUS_PENDING = "pending"
    STATUS_ALIGNED = "aligned"
    STATUS_UNALIGNED = "unaligned"
    STATUS_ERROR = "error"

    # Submission state choices
    SUB_STATE_IN_PROGRESS = "in-progress"
    SUB_STATE_COMPLETED = "completed"
    SUB_STATE_ERROR = "error"

    # Submission op choices
    SUB_OP_ELIGIBILITY = "check-eligibility"
    SUB_OP_ALIGN = "align"
    SUB_OP_UNALIGN = "unalign"
    SUB_OP_REPORT_DATA = "report-data"

    # Report-data result codes — ACCESSReportDataResultVS value set (OM v0.9.11 p.82).
    REPORT_SUCCESS = "success"
    REPORT_VALIDATION_ERROR = "validation-error"
    REPORT_DUPLICATE = "duplicate"
    REPORT_PATIENT_NOT_ALIGNED = "patient-not-aligned"
    REPORT_PERIOD_CLOSED = "reporting-period-closed"
    REPORT_INCOMPLETE_DATA = "incomplete-data"
    REPORT_INCORRECT_TRACK = "incorrect-track"

    # Unalignment reason choices — ACCESSUnalignmentReasonCS value set (OM v0.9.11).
    UNALIGN_REASON_GEOGRAPHIC_RELOCATED = "geographic-relocated"
    UNALIGN_REASON_LOSS_OF_CONTACT = "loss-of-contact"
    UNALIGN_REASON_NO_LONGER_CLINICALLY_ELIGIBLE = "no-longer-clinically-eligible"
    UNALIGN_REASON_PATIENT_INITIATED = "patient-initiated"
