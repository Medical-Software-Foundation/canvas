"""ExportJob — persisted record of a per-patient EHI export.

One row per ``$export`` run so the workspace can show each patient's last
export state and re-download a completed job's files without kicking off a new
export. The ``output`` JSON holds the bulkstatus file URLs as a snapshot; the
authoritative URLs are still re-fetched from bulkstatus by ``job_id`` at
download time (they can expire), so this record is for visibility + resume.
"""

from canvas_sdk.v1.data import ModelExtension, Patient, Staff
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    TextField,
)


class CustomPatient(Patient, ModelExtension):
    """Plugin-private handle on Patient so a CustomModel FK can target dbid."""


class CustomStaff(Staff, ModelExtension):
    """Plugin-private handle on Staff so a CustomModel FK can target dbid."""


class ExportJob(CustomModel):
    """A single patient EHI export run and its current status."""

    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="ehi_export_jobs",
    )
    # Groups all jobs kicked off by one "Export selected" click, so the workspace
    # can show a run and offer a single ZIP once its patients finish. Empty for
    # legacy rows created before batching.
    batch_id = TextField(default="")
    # The staff member who kicked off this export. Nullable for legacy rows and
    # any future non-interactive creation path. FK so the name stays current.
    started_by = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="started_ehi_exports",
        null=True,
    )
    job_id = TextField()
    status = TextField()  # "in-progress" | "complete" | "error"
    output = JSONField(default=list)  # bulkstatus output: [{"type": ..., "url": ...}, ...]
    # S3 object key of the prepared per-patient JSON, set once uploaded. Empty
    # until the cron (or an on-demand download) has merged + stored the bundle.
    s3_key = TextField(default="")
    attempts = IntegerField(default=0)
    last_error = TextField(default="")
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["job_id"]),
            Index(fields=["patient", "-updated_at"]),
            Index(fields=["status"]),
            Index(fields=["batch_id", "-created_at"]),
        ]
