"""ExportStorage — thin wrapper over the Canvas SDK S3 client for EHI exports.

Each completed patient export is stored as one JSON object under
``<prefix>/<batch_id>/<Last_First>_<patient_id>.json``. Downloads are served as
short-lived presigned URLs so the browser pulls directly from S3 (no plugin
memory, no in-browser ZIP). The plugin sandbox blocks zipfile/zlib/io, so a
combined archive isn't built here — files are delivered per patient.
"""

from __future__ import annotations

import re

from canvas_sdk.clients.aws import Credentials, S3
from logger import log

_DEFAULT_PREFIX = "ehi-exports"
_PRESIGN_TTL_SECONDS = 3600  # 1 hour
_REQUIRED = ("S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_REGION", "S3_BUCKET")


def _safe_segment(value: str, fallback: str = "unknown") -> str:
    """Sanitize a string for use in an S3 key segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip()).strip("_")
    return cleaned[:120] or fallback


class ExportStorage:
    """S3-backed storage for prepared per-patient export JSON."""

    def __init__(self, client: S3, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    @classmethod
    def from_secrets(cls, secrets: dict) -> "ExportStorage | None":
        """Build from plugin secrets, or return None if S3 isn't configured."""
        if not all(secrets.get(name) for name in _REQUIRED):
            return None
        client = S3(
            Credentials(
                key=secrets["S3_ACCESS_KEY"],
                secret=secrets["S3_SECRET_KEY"],
                region=secrets["S3_REGION"],
                bucket=secrets["S3_BUCKET"],
            )
        )
        prefix = (secrets.get("S3_PREFIX") or _DEFAULT_PREFIX).strip("/")
        return cls(client, prefix)

    @staticmethod
    def is_configured(secrets: dict) -> bool:
        """Whether all required S3 secrets are present."""
        return all(secrets.get(name) for name in _REQUIRED)

    def patient_key(self, batch_id: str, patient_id: str, patient_name: str = "") -> str:
        """Build the S3 object key for a patient's export NDJSON."""
        return self._object_key(batch_id, patient_id, patient_name, "ndjson")

    def ccda_key(self, batch_id: str, patient_id: str, patient_name: str = "") -> str:
        """Build the S3 object key for a patient's C-CDA XML document."""
        return self._object_key(batch_id, patient_id, patient_name, "xml")

    def _object_key(self, batch_id: str, patient_id: str, patient_name: str, ext: str) -> str:
        folder = _safe_segment(batch_id, fallback="unbatched")
        name = _safe_segment(f"{patient_name}_{patient_id}".strip("_"), fallback=patient_id)
        return f"{self._prefix}/{folder}/{name}.{ext}"

    def batch_prefix(self, batch_id: str) -> str:
        """The S3 key prefix for an entire run (for `aws s3 sync`)."""
        return f"{self._prefix}/{_safe_segment(batch_id, fallback='unbatched')}/"

    def upload_ndjson(self, object_key: str, ndjson_text: str) -> bool:
        """Upload prepared NDJSON text as application/x-ndjson. Returns True on success."""
        return self._upload(object_key, ndjson_text, "application/x-ndjson")

    def upload_xml(self, object_key: str, xml_text: str) -> bool:
        """Upload a prepared C-CDA document as application/xml. Returns True on success."""
        return self._upload(object_key, xml_text, "application/xml")

    def _upload(self, object_key: str, text: str, content_type: str) -> bool:
        response = self._client.upload_binary_to_s3(
            object_key, text.encode("utf-8"), content_type
        )
        ok = bool(response and getattr(response, "ok", False))
        if not ok:
            status = getattr(response, "status_code", "no response")
            log.error("ExportStorage: upload to %s failed (%s)", object_key, status)
        return ok

    def presigned_url(self, object_key: str, ttl: int = _PRESIGN_TTL_SECONDS) -> str | None:
        """Generate a presigned GET URL for an object."""
        return self._client.generate_presigned_url(object_key, ttl)
