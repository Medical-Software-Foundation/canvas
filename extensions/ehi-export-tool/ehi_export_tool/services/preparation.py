"""prepare_job — ensure a completed export's JSON is stored in S3.

Shared by the background cron (which prepares completed jobs proactively) and the
on-demand download endpoint (which prepares a single job if the user clicks
before the cron gets to it). Either way the heavy work — merging the patient's
NDJSON files into one JSON — happens server-side for a single patient, never a
big in-memory archive.
"""

from __future__ import annotations

import json

from logger import log

from ehi_export_tool.services.export_jobs import ExportJobService
from ehi_export_tool.services.storage import ExportStorage
from ehi_export_tool.utils.fhir_client import EHIExportClient


class PreparationResult:
    """Outcome of a prepare attempt."""

    READY = "ready"  # s3_key is set (already or just uploaded)
    PENDING = "pending"  # job not complete yet
    FAILED = "failed"  # build/upload failed

    def __init__(self, status: str, s3_key: str = "") -> None:
        self.status = status
        self.s3_key = s3_key


def prepare_job(client: EHIExportClient, storage: ExportStorage, job) -> PreparationResult:
    """Ensure ``job``'s patient JSON is in S3; return its key / state.

    - If already uploaded (``job.s3_key``), returns READY with that key.
    - Otherwise re-polls bulkstatus: if complete, merges + uploads, records the
      key, returns READY; if still processing, returns PENDING.
    Raises ``EHIExportError`` only on FHIR failures the caller should surface.
    """
    if job.s3_key:
        return PreparationResult(PreparationResult.READY, job.s3_key)

    status = client.get_status(job.job_id)
    if status["status"] != "complete":
        # Keep the persisted status in step (also advances attempts/updated_at).
        ExportJobService.update_status(job.job_id, status["status"], output=status.get("output"))
        return PreparationResult(PreparationResult.PENDING)

    bundle = client.build_patient_bundle(str(job.patient.id), status["output"])
    key = storage.patient_key(
        batch_id=job.batch_id,
        patient_id=str(job.patient.id),
        patient_name=_patient_name(job.patient),
    )
    if not storage.upload_json(key, json.dumps(bundle)):
        ExportJobService.update_status(
            job.job_id, "complete", output=status["output"], error="S3 upload failed"
        )
        return PreparationResult(PreparationResult.FAILED)

    ExportJobService.mark_uploaded(job.job_id, key, output=status["output"])
    log.info("prepare_job: uploaded export for patient %s to %s", job.patient.id, key)
    return PreparationResult(PreparationResult.READY, key)


def _patient_name(patient) -> str:
    last = (getattr(patient, "last_name", "") or "").strip()
    first = (getattr(patient, "first_name", "") or "").strip()
    return f"{last}_{first}".strip("_")
