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

    # Unalignment reason choices
    UNALIGN_REASON_PATIENT_REQUEST = "patient-request"
    UNALIGN_REASON_PROVIDER_DECISION = "provider-decision"
    UNALIGN_REASON_CARE_COMPLETED = "care-completed"
    UNALIGN_REASON_OTHER = "other"
