from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel
from cms_access_fhir_client.models.access_alignment import CustomPatient


class ACCESSOperationLog(CustomModel):
    """Append-only audit log of every CMS ACCESS operation event.

    Unlike ACCESSAlignment (one mutable row per patient/track that always reflects the
    *latest* state), this table keeps one immutable row per operation event — every
    submission and every terminal result — so the full per-operation history is preserved
    and reportable via SQL. The result_code/result_system columns capture which CMS value
    set the code came from (Eligibility / Alignment / Unalignment / ReportData ResultVS),
    since e.g. `patient-not-aligned` appears in more than one system with different meaning.
    """

    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="access_operation_logs",
    )
    track = TextField(default="")
    operation = TextField(default="")
    phase = TextField(default="")
    result_code = TextField(default="")
    result_system = TextField(default="")
    http_status = IntegerField(default=0)
    detail = TextField(default="")
    content_location = TextField(default="")
    exchange = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=["operation"]),
            Index(fields=["track"]),
            Index(fields=["result_code"]),
            Index(fields=["-created_at"]),
        ]

    # Phase choices — where in the async lifecycle this event was recorded.
    PHASE_SUBMITTED = "submitted"   # 202 accepted; awaiting poll
    PHASE_RESULT = "result"         # terminal business result (HTTP 200 + result code)
    PHASE_ERROR = "error"           # technical/processing error (OperationOutcome, abandon)

    # Result code systems (ACCESS value sets, OM v0.9.11) — recorded alongside the code so
    # reports can tell which lifecycle a code belongs to.
    SYSTEM_ELIGIBILITY = "ACCESSEligibilityResultVS"
    SYSTEM_ALIGNMENT = "ACCESSAlignmentResultVS"
    SYSTEM_UNALIGNMENT = "ACCESSUnalignmentResultVS"
    SYSTEM_REPORT_DATA = "ACCESSReportDataResultVS"

    # operation → result value set, for callers that have the operation constant.
    SYSTEM_FOR_OP = {
        "check-eligibility": SYSTEM_ELIGIBILITY,
        "align": SYSTEM_ALIGNMENT,
        "unalign": SYSTEM_UNALIGNMENT,
        "report-data": SYSTEM_REPORT_DATA,
    }
